"""
Functions used to transform downloaded data into BIDS format
"""
import json
import os
import re
import tempfile
import zipfile
import logging

LOG = logging.getLogger(__name__)

def get_echo_num(fname, json_data):
    """
    Try to identify the echo number if possible
    """
    echo_res = [re.compile(".*_echo(\d+)[_$]"), re.compile(".*_e(\d+)[_$]")]
    if "EchoNumber" in json_data:
        return json_data["EchoNumber"]

    for echo_re in echo_res:
        match = echo_re.match(fname.lower())
        if match:
            return int(match.group(1))

def get_coil_num(fname, json_data):
    pattern = re.compile(".*coil(\d+).*")
    match= pattern.match(fname.lower())
    if match:
        return int(match.group(1))

# Matchers return tuple of (subfolder, suffix, dict of additional filename attributes, dict of json updates)
# or None if file did not match
def match_anat(fname, json_data):
    """
    Match anatomical images
    """
    folder, suffix, attrs, md = "anat", None, {}, {}
    desc = json_data.get("SeriesDescription", "").lower()
    if "t1" in desc:
        suffix = "T1w"
    elif "t2star" in desc:
        suffix = "T2starw"
    elif "t2" in desc:
        suffix = "T2w"

    if suffix:
        img_types = [s.upper() for s in json_data.get("ImageType", [])]
        if "NORM" in img_types:
            attrs["acq"] = "norm"
        if "PHASE" in img_types:
            attrs["part"] = "phase"
        if fname.lower().endswith("_ph"):
            attrs["part"] = "phase"

        echonum = get_echo_num(fname, json_data)
        if echonum:
            attrs["echo"] = echonum

def match_func(fname, json_data):
    """
    Match functional images
    """
    folder, suffix, attrs, md = "func", None, {}, {}
    desc = json_data.get("SeriesDescription", "").lower()
    if "fmri" in desc:
        if "sbref" in desc:
            suffix = "sbref"
        else:
            suffix = "bold"

        if "resting" in desc:
            attrs["task"] = "rest"
        elif "task" in desc:
            attrs["task"] = "task"
            md["TaskName"] = "task"
        
        return folder, suffix, attrs, md

def match_dwi(fname, json_data):
    """
    Match DWI images
    """
    folder, suffix, attrs, md = "dwi", None, {}, {}
    desc = json_data.get("SeriesDescription", "").lower()
    if "diff" in desc:
        if "sbref" in desc:
            suffix = "sbref"
        else:
            suffix = "dwi"

        return folder, suffix, attrs, md

def match_swi(fname, json_data):
    """
    Match SWI images
    """
    folder, suffix, attrs, md = "swi", None, {}, {}
    desc = json_data.get("SeriesDescription", "").lower()
    if "swi" in desc:
        if "sbref" in desc:
            suffix = "sbref"
        else:
            suffix = "swi"

        echonum = get_echo_num(fname, json_data)
        if echonum:
            attrs["echo"] = echonum

        coilnum = get_coil_num(fname, json_data)
        if coilnum:
            attrs["coil"] = coilnum

        return folder, suffix, attrs, md

DEFAULT_MATCHER = [
    match_anat,
    match_func,
    match_dwi,
    match_swi,
]

def update_ptlist(bidsdir, bids_subject, subject):
    """
    Update participants list

    FIXME no additional pt data currently written
    """
    pts_file = os.path.join(bidsdir, "participants.tsv")
    if os.path.exists(pts_file):
        with open(pts_file) as f:
            pts = [l.strip() for l in f.readlines()]
    else:
        pts = ["participant_id",]

    if bids_subject not in pts[1:]:
        pts.append(bids_subject)
        with open(pts_file, "w") as f:
            for pt in pts:
                f.write("%s\n" % pt)

TEMPLATE_DATASET_DESC = {
  "Name": None,
  "BIDSVersion": "1.4.0",
  "DatasetType": "raw",
}

def check_dataset_description(bidsdir, project):
    """
    Check the dataset description file exists and write it if not
    """
    desc_file = os.path.join(bidsdir, "dataset_description.json")
    if not os.path.exists(desc_file):
        dataset_desc = dict(TEMPLATE_DATASET_DESC)
        dataset_desc["Name"] = project.label()
        with open(desc_file, 'w') as f:
            json.dump(dataset_desc, f)

    readme_file = os.path.join(bidsdir, "README")
    if not os.path.exists(readme_file):
        readme = """This data set was downloaded from:
    XNAT=%s
    PROJECT=%s""" % ("XNAT", project.label())
        with open(readme_file, 'w') as f:
            f.write(readme)

def download_bids(obj, obj_type, args, path):
    if obj_type != "scan":
        # Only download individual scans
        return

    print("Downloading %s: %s in BIDS format" % (obj_type, obj.label()))
    r = obj.resource(args.download_resource)
    exp = obj.parent()
    subj = exp.parent()
    proj = subj.parent()
    
    # BIDS does not allow hyphen or underscore in IDs
    bids_project = proj.label().replace("_", "").replace("-", "")
    bids_subject = "sub-" + subj.label().replace("_", "").replace("-", "")
    bids_session = "ses-" + exp.label().replace("_", "").replace("-", "")

    bidsdir = os.path.join(args.download, bids_project)
    outdir = os.path.join(bidsdir, bids_subject, bids_session)
    os.makedirs(outdir, exist_ok=True)
      
    bids_mapper = DEFAULT_MATCHER # FIXME use args.bids_mapper

    update_ptlist(bidsdir, bids_subject, subj)
    check_dataset_description(bidsdir, proj)

    # Download the NIFTI data and metadata
    # Set of all file name without extensions. Since we're dealing with
    # a single scan there will normally be only one
    imgfiles = set()

    # Copy expected files to output dir. Not given standard names or subfolders yet
    EXTS = (".nii.gz", ".nii", ".json", ".bval", ".bvec")
        
    for idx, f in enumerate(r.files()):
        #f.get(os.path.join(download_path, f.label()))
        name = f.label()
        imgname = os.path.basename(name)
        for ext in EXTS:
            imgname = imgname.replace(ext, "")
        imgfiles.add(imgname)
        f.get(os.path.join(outdir, os.path.basename(name)))

    # Rename files according to matcher rules
    for imgname in imgfiles:
        json_fname = os.path.join(outdir, imgname + ".json")
        if not os.path.exists(json_fname):
            LOG.warn(f"No JSON sidecar for {imgname} - may not be able to match file")
            json_data = {}
        else:
            try:
                with open(os.path.join(outdir, imgname + ".json")) as json_file:
                    json_data = json.load(json_file)
            except Exception as exc:
                LOG.warn("Error reading JSON metadat: %s - may not be able to match file", str(exc))
                json_data = {}
        found = False
        for matcher in bids_mapper:
            bids_match = matcher(imgname, json_data)
            if bids_match:
                folder, suffix, attrs, md = bids_match
                os.makedirs(os.path.join(outdir, folder), exist_ok=True)
                handled_duplicates = False
                for ext in EXTS:
                    src_fname = os.path.join(outdir, imgname + ext)
                    while not handled_duplicates:
                        # Ugly code to avoid overwriting existing files with same name by adding the
                        # BIDS 'run' attribute to distinguish between them
                        bids_fname = "_".join(["%s-%s" % (k, v) for k, v in attrs.items()] + [suffix])
                        dest_fname = os.path.join(outdir, folder, "%s_%s_%s%s" % (bids_subject, bids_session, bids_fname, ext))
                        if os.path.exists(dest_fname):
                            if "run" not in attrs:
                                # Existing file lacks the 'run' attribute so first we need to designate it as 'run 1', then
                                # the new conflicting file can be tried out as 'run 2'
                                attrs["run"] = 1
                                rename_existing_bids_fname = "_".join(["%s-%s" % (k, v) for k, v in attrs.items()] + [suffix])
                                rename_existing_dest_fname = os.path.join(outdir, folder, "%s_%s_%s%s" % (bids_subject, bids_session, rename_existing_bids_fname, ext))
                                os.rename(dest_fname, rename_existing_dest_fname)
                                attrs["run"] = 2
                            else:
                                attrs["run"] += 1
                        else:
                            # Can now use the run attribute for all extensions
                            print(f"Mapping {imgname} -> {folder} / {bids_fname}")
                            handled_duplicates = True

                    if os.path.exists(src_fname):
                        os.rename(src_fname, dest_fname)
                found = True
                break
        if not found:
            LOG.warn(f"Unmatched file: {imgname} - removing from BIDS dataset")
            for ext in EXTS:
                if os.path.exists(os.path.join(outdir, imgname + ext)):
                    os.remove(os.path.join(outdir, imgname + ext))
