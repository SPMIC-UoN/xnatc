import json
import os
import tempfile
import zipfile

def match_anat(fname, json_data):
    """
    Match anatomical images
    """
    fname = None
    desc = json_data["SeriesDescription"].lower()
    if "t1" in desc:
        fname = "T1w"
    elif "t2" in desc:
        fname = "T2w"

    if fname:
        if "NORM" in json_data["ImageType"]:
            fname = "acq-NORM_" + fname
        return "anat", fname

def match_func(fname, json_data):
    """
    Match functional images
    """
    folder, fname = None, None
    desc = json_data["SeriesDescription"].lower()
    if "fmri" in desc:
        folder = "func"
        if "sbref" in desc:
            fname = "sbref"
        else:
            fname = "bold"

        if "resting" in desc:
            fname = "task-rest_" + fname
        elif "task" in desc:
            fname = "task-on_" + fname
        
        return folder, fname

def match_diff(fname, json_data):
    """
    Match DWI images
    """
    folder, fname = None, None
    desc = json_data["SeriesDescription"].lower()
    if "diff" in desc:
        folder = "dwi"
        if "sbref" in desc:
            fname = "sbref"
        else:
            fname = "dwi"

        return folder, fname

def match_swi(fname, json_data):
    """
    Match SWI images
    """
    folder, fname = None, None
    desc = json_data["SeriesDescription"].lower()
    if "swi" in desc:
        folder = "swi"
        if "sbref" in desc:
            fname = "sbref"
        else:
            fname = "swi"

        if "EchoNumber" in json_data:
            fname = "echo-%i_" % json_data["EchoNumber"] + fname 

        return folder, fname

DEFAULT_MATCHER = [
    match_anat,
    match_func,
    match_diff,
]

def download_bids(resource, args):
    bids_mapper = DEFAULT_MATCHER # FIXME use args.bids_mapper

    # BIDS does not allow hyphen or underscore in IDs
    bids_project = args.cur_project.replace("_", "").replace("-", "")
    bids_subject = args.cur_subject.replace("_", "").replace("-", "")
    bids_session = args.cur_experiment.replace("_", "").replace("-", "")
    outdir = os.path.join(args.download, bids_project, "sub-" + bids_subject, "ses-" + bids_session)
    os.makedirs(outdir, exist_ok=True)

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
                    bids_subdir, bids_fname = bids_match
                    os.makedirs(os.path.join(outdir, bids_subdir), exist_ok=True)
                    for ext in EXTS:
                        src_fname = os.path.join(outdir, imgname + ext)
                        dest_fname = os.path.join(outdir, bids_subdir, "sub-%s_ses-%s_%s%s" % (bids_subject, bids_session, bids_fname, ext))
                        if os.path.exists(src_fname):
                            os.rename(src_fname, dest_fname)
                    found = True
                    break
            if not found:
                print("WARNING: Unmatched file: %s - removing from BIDS dataset" % imgname)
                for ext in EXTS:
                    if os.path.exists(os.path.join(outdir, imgname + ext)):
                        os.remove(os.path.join(outdir, imgname + ext))
