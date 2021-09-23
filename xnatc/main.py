"""
xnatc - Command line interface to XNAT
"""
import argparse
import fnmatch
import getpass
import netrc
import os
import re
import sys
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
        return obj.label
    elif hasattr(obj, "xnat_url"):
        return obj.xnat_url
    else:
        return obj.id

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
    outdir = os.path.join(args.download, args.cur_project, args.cur_subject, args.cur_experiment, args.cur_scan)
    os.makedirs(outdir)
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

def main():
    parser = argparse.ArgumentParser(description='Command line interface to XNAT')
    parser.add_argument('--xnat', default='https://xnatpriv.nottingham.ac.uk/', help='xnat host URL')
    parser.add_argument('--user', help='XNAT user name. If not specified will use credentials from $HOME.netrc or prompt for username')
    parser.add_argument('--password', help='XNAT password. If not specified will use credentials from $HOME.netrc or prompt for password')
    parser.add_argument('--project', help='Project ID')
    parser.add_argument('--subject', help='Subject ID')
    parser.add_argument('--experiment', help='Experiment ID')
    parser.add_argument('--scan', help='Scan ID')
    parser.add_argument('--assessor', help='Assessor ID')
    parser.add_argument('--resource', help='Name of resource to download', default='DICOM')
    parser.add_argument('--download', help='Download data to named directory')
    parser.add_argument('--download-format', help='Download format', default="xnat", choices=["xnat", "bids"])
    parser.add_argument('--bids-mapper', help='BIDS mapper', default="default")
    parser.add_argument('--upload', help='Upload data to an assessor')
    parser.add_argument('--upload-type', help='Data type to upload data - if not specified will try to autodetect')
    parser.add_argument('--upload-name', help='Name to give uploaded data - defaults to file basename')
    parser.add_argument('--recurse', action="store_true", help='Recursively list contents of selected object')
    parser.add_argument('--match-type', help='Type of matching', choices=['glob', 're'], default='glob')
    parser.add_argument('--match-files', action="store_true", help='Allow subject/experiment/scan etc to be file names containing ID lists')
    args = parser.parse_args()
    args.list_children = True

    get_auth(args)

    with xnat.connect(args.xnat, user=args.user, password=args.password) as connection:
        connection.xnat_url = args.xnat
        if args.download and not (args.project and args.subject and args.experiment):
            check = input("WARNING: download requested for multiple experiment - are you sure? ")
            if check.lower() not in ("y", "yes"):
                sys.exit(0)
        if args.scan and args.assessor:
            raise ValueError("Can't specify both a scan and an assessor")
        elif args.scan:
            args.assessor = "skip"
        elif args.assessor:
            args.scan = "skip"

        if args.download:
            args.recurse = True
            args.downloader = get_downloader(args.download_format)
            if args.download_format == "bids" and not args.resource == "NIFTI":
                print("WARNING: Setting download resource to NIFTI as required for BIDS")
                args.resource = "NIFTI"

        process(connection, args, HIERARCHY[0][0], 0)
        if args.download:
            print("Data downloaded to %s" % args.download)

def process(obj, args, obj_type, hierarchy_idx, indent=""):
    print("%s%s: %s" % (indent, obj_type.capitalize(), label(obj)))
    setattr(args, "cur_" + obj_type, label(obj))

    if hierarchy_idx == len(HIERARCHY)-1:
        # At the bottom level, i.e. scan/assessor
        if args.download:
            if args.resource in obj.resources:
                res = obj.resources[args.resource]
                args.downloader(res, args)
            else:
                print("WARNING: %s %s does not have an associated resource named %s" % (obj_type.capitalize(), label(obj), args.resource))

        if args.upload:
            if not args.upload_type and (args.upload.lower().endswith(".nii") or args.upload.lower().endswith(".nii.gz")):
                args.upload_type = 'NIFTI'
            else:
                print("WARNING: unrecognized resource %s - will not upload")

            if args.upload_type not in obj.resources:
                resource = obj.xnat_session.classes.ResourceCatalog(parent=obj, label=args.upload_type)
            else:
                resource = obj.resources[args.upload_type]
            
            if not args.upload_name:
                args.upload_name = os.path.basename(args.upload)

            resource.upload(args.upload, os.path.basename(args.upload))
            print("%s - Uploaded %s as %s" % (indent, args.upload, args.upload_name))
            
    else:
        for child_type in HIERARCHY[hierarchy_idx+1]:
            children = getattr(obj, child_type + "s")
            match_id = getattr(args, child_type)
            for child_id, child in children.items():
                if matches(child_id, match_id, args):
                    process(child, args, child_type, hierarchy_idx+1, indent+"  ")

def matches(child_id, match_id, args):
    if match_id == "skip":
        return False
    elif match_id is None:
        return args.recurse

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
