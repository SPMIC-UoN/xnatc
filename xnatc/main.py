"""
xnatc - Command line interface to XNAT
"""
import argparse
import fnmatch
import getpass
import netrc
import os
import re
import requests
import tempfile
from urllib.parse import urlparse
import zipfile

import xnat

from . import bids

HIERARCHY = [
    ["xnat"],
    ["project"],
    ["subject"],
    ["experiment"],
    ["scan", "assessor"],
]

def label(obj):
    if hasattr(obj, "label"):
        label = obj.label
    elif hasattr(obj, "name"):
        label = obj.name
    elif hasattr(obj, "xnat_url"):
        label = obj.xnat_url
    else:
        label = obj.id
    return label, getattr(obj, "id", label)

def get_auth(args):
    if args.user and args.password:
        return
    if '//' not in args.xnat:
        print("WARNING: Xnat host did not have HTTP or HTTPS specified - assuming HTTPS")
        args.xnat = 'https://' + args.xnat
    url = urlparse(args.xnat)
    auth_data = netrc.netrc()
    if url.hostname in auth_data.hosts:
        args.user, _account, args.password = auth_data.authenticators(url.hostname)
    else:
        print("WARNING: No authentication information found in $HOME/.netrc")
        args.user = input("Username: ").strip()
        args.password = getpass.getpass()
        print("  Note: You can add your credentials to $HOME/.netrc for automatic login")
        print("        See https://xnat.readthedocs.io/en/latest/static/tutorial.html#credentials")

def download_xnat(resource, args):
    """
    Download resource in 'XNAT' structure - i.e. directory tree of project/subject/experiment/scan/
    """
    outdir = os.path.join(args.download, args.cur_project[0], args.cur_subject[0], args.cur_experiment[0], args.cur_scan[0])
    os.makedirs(outdir, exist_ok=True)
    with tempfile.TemporaryDirectory() as d:
        fname = os.path.join(d, "res.zip")
        resource.download(fname)
        archive = zipfile.ZipFile(fname)
        for name in archive.namelist():
            with open(os.path.join(outdir, os.path.basename(name)), "wb") as outfile:
                contents = archive.open(name)
                outfile.write(contents.read())

def get_downloader(format):
    if format == "xnat":
        return download_xnat
    elif format == "bids":
        return bids.download_bids
    else:
        raise ValueError("Unrecognized download format: %s" % format)

def upload_dir(obj, dirname, default_resource_type=None, indent=""):
    print("%s - Uploading contents of %s" % (indent, dirname))
    for fname in os.listdir(dirname):
        fpath = os.path.join(dirname, fname)
        if os.path.isdir(fpath):
            for sub_fname in os.listdir(fpath):
                sub_fpath = os.path.join(fpath, sub_fname)
                upload_file(obj, sub_fpath, resource_type=fname, indent=indent+"  ")
        else:
            upload_file(obj, fpath, resource_type=default_resource_type, indent=indent+"  ")

def upload_file(obj, fname, resource_type=None, upload_name=None, indent=""):
    if not resource_type and (fname.lower().endswith(".nii") or fname.lower().endswith(".nii.gz")):
        resource_type = 'NIFTI'

    if resource_type:
        if resource_type not in obj.resources:
            resource = obj.xnat_session.classes.ResourceCatalog(parent=obj, label=resource_type)
        else:
            resource = obj.resources[resource_type]

        if not upload_name:
            upload_name = os.path.basename(fname)

        resource.upload(fname, upload_name)
        print("%s - Uploaded %s as %s/%s" % (indent, fname, resource_type, upload_name))
    else:
        print("WARNING: Could not detect resource type for %s - will not upload" % fname)

def main():
    parser = argparse.ArgumentParser(description='Command line interface to XNAT')
    parser.add_argument('--xnat', default='https://xnatpriv.nottingham.ac.uk/', help='xnat host URL')
    parser.add_argument('--user', help='XNAT user name. If not specified will use credentials from $HOME.netrc or prompt for username')
    parser.add_argument('--password', help='XNAT password. If not specified will use credentials from $HOME.netrc or prompt for password')
    parser.add_argument('--project', help='Project name/ID')
    parser.add_argument('--subject', help='Subject name/ID')
    parser.add_argument('--experiment', help='Experiment name/ID')
    parser.add_argument('--scan', help='Scan ID')
    parser.add_argument('--assessor', help='Assessor name/ID')
    parser.add_argument('--download', help='Download data to named directory')
    parser.add_argument('--download-resource', help='Name of resource type to download', default='DICOM')
    parser.add_argument('--download-format', help='Download format', default="xnat", choices=["xnat", "bids"])
    #parser.add_argument('--bids-mapper', help='BIDS mapper', default="default")
    parser.add_argument('--upload', help='File or directory containing data to upload to a scan/assessor')
    parser.add_argument('--upload-resource', help='Resource type for uploaded data - if not specified will try to autodetect from file type')
    parser.add_argument('--upload-name', help='Name to give uploaded data - defaults to file basename')
    #parser.add_argument('--assessor-type', help='Assessor type to create on upload if it does not already exist', default="PipelineData")
    parser.add_argument('--create-assessor', help='File containing XML definition of assessor to create')
    parser.add_argument('--match-type', help='Type of matching', choices=['glob', 're'], default='glob')
    parser.add_argument('--match-files', action="store_true", help='Allow subject/experiment/scan etc to be file names containing ID lists')
    parser.add_argument('--debug', action="store_true", help='Enable debug mode')
    args = parser.parse_args()
    args.list_children = True

    get_auth(args)

    with xnat.connect(args.xnat, user=args.user, password=args.password, debug=args.debug) as connection:
        connection.xnat_url = args.xnat
        if args.scan and not args.assessor:
            args.assessor = "skip"
        elif args.assessor and not args.scan:
            args.scan = "skip"

        if args.download:
            args.downloader = get_downloader(args.download_format)
            if args.download_format == "bids" and not args.download_resource == "NIFTI":
                print("WARNING: Setting download resource to NIFTI as required for BIDS")
                args.download_resource = "NIFTI"
        elif args.upload and (not args.project or not args.subject or not args.experiment or not (args.scan or args.assessor)):
            raise RuntimeError("To upload data you must fully specify a project, subject, experiment and either a scan or an assessor")

        process(connection, args, HIERARCHY[0][0], 0)
        if args.download:
            print("Data downloaded to %s" % args.download)

def process(obj, args, obj_type, hierarchy_idx, indent=""):
    print("%s%s: %s" % (indent, obj_type.capitalize(), label(obj)[0]))
    setattr(args, "cur_" + obj_type, (label(obj)[0], obj))

    if hierarchy_idx == len(HIERARCHY)-1:
        # At the bottom level, i.e. scan/assessor
        if args.download:
            if args.download_resource in obj.resources:
                res = obj.resources[args.download_resource]
                try:
                    args.downloader(res, args)
                except Exception as exc:
                    print("WARNING: Failed to download resource %s from %s %s: %s" % (args.download_resource, obj_type.capitalize(), label(obj)[0], str(exc)))
            else:
                print("WARNING: %s %s does not have an associated resource named %s" % (obj_type.capitalize(), label(obj)[0], args.download_resource))

        if args.upload:
            if os.path.isdir(args.upload):
                upload_dir(obj, args.upload, args.upload_resource, indent)
            else:
                upload_file(obj, args.upload, args.upload_resource, args.upload_name, indent)
    elif args.create_assessor and obj_type == "experiment":
        # We have been asked to create an assessor using the given XML document
        # Unfortunately xnat_session.post doesn't seem to handle files? So use requests directly
        print("%s - Creating new assessor using XML: %s" % (indent, args.create_assessor))
        with open(args.create_assessor) as xmldata:
            requests.post("%s/%s/assessors" % (args.xnat, obj.uri), files={"file" : xmldata})
    else:
        match = False
        for child_type in HIERARCHY[hierarchy_idx+1]:
            children = getattr(obj, child_type + "s")
            match_id = getattr(args, child_type)
            for child in children.values():
                for lbl in label(child):
                    if matches(lbl, match_id, args):
                        process(child, args, child_type, hierarchy_idx+1, indent+"  ")
                        match = True
                        break
        if not match and args.upload and obj_type == "experiment":
            # When uploading we may need to create the assessor if it doesn't currently exist
            print("%s - Creating new assessor %s (%s) as currently does not exist" % (indent, args.assessor if args.assessor else args.scan, args.assessor_type))
            assessor = getattr(obj.xnat_session.classes, args.assessor_type)(parent=obj, label=args.assessor if args.assessor else args.scan)
            process(assessor, args, "assessor" if args.assessor else "scan", hierarchy_idx+1, indent+"  ")

def matches(child_id, match_id, args):
    if match_id == "skip":
        return False
    elif match_id is None:
        return True

    if args.match_files and os.path.exists(match_id):
        with open(match_id) as f:
            match_ids = [l.strip() for l in f.readlines()]
    else:
        match_ids = [match_id]

    for match_id in match_ids:
        if args.match_type == "glob":
            match_id = fnmatch.translate(match_id)

        p = re.compile(match_id)
        if p.match(child_id):
            return True

    return False

if __name__ == '__main__':
    main()
