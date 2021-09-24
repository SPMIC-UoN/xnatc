"""
Functions used to transform downloaded data into BIDS format
"""
import json
import os
import re
import tempfile
import zipfile

# Matchers return tuple of (subfolder, suffix, dict of additional filename attributes, dict of json updates)
# or None if file did not match

def match_anat(fname, json_data):
    """
    Match anatomical images
    """
    folder, suffix, attrs, md = "anat", None, {}, {}
    desc = json_data["SeriesDescription"].lower()
    if "t1" in desc:
        suffix = "T1w"
    elif "t2" in desc:
        suffix = "T2w"

    if suffix:
        if "NORM" in json_data["ImageType"]:
            attrs["acq"] = "NORM"
        return folder, suffix, attrs, md

def match_func(fname, json_data):
    """
    Match functional images
    """
    folder, suffix, attrs, md = "func", None, {}, {}
    desc = json_data["SeriesDescription"].lower()
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
    desc = json_data["SeriesDescription"].lower()
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
    desc = json_data["SeriesDescription"].lower()
    if "swi" in desc:
        if "sbref" in desc:
            suffix = "sbref"
        else:
            suffix = "swi"

        if "EchoNumber" in json_data:
            attrs["echo"] = json_data["EchoNumber"]

        pattern = re.compile(".*coil(\d+).*")
        match= pattern.match(fname.lower())
        if match:
            coil = int(match.group(1))
            attrs["coil"] = coil

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

def check_dataset_description(bidsdir, args):
    """
    Check the dataset description file exists and write it if not
    """
    desc_file = os.path.join(bidsdir, "dataset_description.json")
    if not os.path.exists(desc_file):
        dataset_desc = dict(TEMPLATE_DATASET_DESC)
        dataset_desc["Name"] = args.cur_project[1].name
        with open(desc_file, 'w') as f:
            json.dump(dataset_desc, f)

    readme_file = os.path.join(bidsdir, "README")
    if not os.path.exists(readme_file):
        readme = """This data set was downloaded from:
    XNAT=%s
    PROJECT=%s""" % (args.cur_xnat[0], args.cur_project[1].name)
        with open(readme_file, 'w') as f:
            f.write(readme)

def download_bids(resource, args):
    bids_mapper = DEFAULT_MATCHER # FIXME use args.bids_mapper

    # BIDS does not allow hyphen or underscore in IDs
    bids_project = args.cur_project[0].replace("_", "").replace("-", "")
    bids_subject = "sub-" + args.cur_subject[0].replace("_", "").replace("-", "")
    bids_session = "ses-" + args.cur_experiment[0].replace("_", "").replace("-", "")
    bidsdir = os.path.join(args.download, bids_project)
    outdir = os.path.join(bidsdir, bids_subject, bids_session)
    os.makedirs(outdir, exist_ok=True)

    update_ptlist(bidsdir, bids_subject, args.cur_subject[1])
    check_dataset_description(bidsdir, args)

    # Download the NIFTI data and metadata
    with tempfile.TemporaryDirectory() as d:
        fname = os.path.join(d, "res.zip")
        resource.download(fname)
        archive = zipfile.ZipFile(fname)

        # Set of all file name without extensions. Since we're dealing with
        # a single scan there will normally be only one
        imgfiles = set()

        # Copy expected files to output dir. Not given standard names or subfolders yet
        EXTS = (".nii.gz", ".nii", ".json", ".bval", ".bvec")
        for name in archive.namelist():
            imgname = os.path.basename(name)
            for ext in EXTS:
                imgname = imgname.replace(ext, "")
            imgfiles.add(imgname)
            with open(os.path.join(outdir, os.path.basename(name)), "wb") as outfile:
                contents = archive.open(name)
                outfile.write(contents.read())

    # Rename files according to matcher rules
    for imgname in imgfiles:
        with open(os.path.join(outdir, imgname + ".json")) as json_file:
            json_data = json.load(json_file)
            found = False
            for matcher in bids_mapper:
                bids_match = matcher(imgname, json_data)
                if bids_match:
                    folder, suffix, attrs, md = bids_match
                    bids_fname = "_".join(["%s-%s" % (k, v) for k, v in attrs.items()] + [suffix])
                    os.makedirs(os.path.join(outdir, folder), exist_ok=True)
                    for ext in EXTS:
                        src_fname = os.path.join(outdir, imgname + ext)
                        dest_fname = os.path.join(outdir, folder, "%s_%s_%s%s" % (bids_subject, bids_session, bids_fname, ext))
                        if os.path.exists(src_fname):
                            os.rename(src_fname, dest_fname)
                    found = True
                    break
            if not found:
                print("WARNING: Unmatched file: %s - removing from BIDS dataset" % imgname)
                for ext in EXTS:
                    if os.path.exists(os.path.join(outdir, imgname + ext)):
                        os.remove(os.path.join(outdir, imgname + ext))
