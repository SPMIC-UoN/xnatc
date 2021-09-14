"""
xnatc - Command line interface to XNAT
"""
import argparse
import getpass
import netrc
import os
import sys
from urllib.parse import urlparse

import xnat

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

def main():
    parser = argparse.ArgumentParser(description='Command line interface to XNAT')
    parser.add_argument('--xnat', default='https://xnatpriv.nottingham.ac.uk/', help='xnat host URL')
    parser.add_argument('--project', help='Project ID')
    parser.add_argument('--subject', help='Subject ID')
    parser.add_argument('--experiment', help='Experiment ID')
    parser.add_argument('--scan', help='Scan ID')
    parser.add_argument('--assessor', help='Assessor ID')
    parser.add_argument('--download', help='Download data to named directory')
    parser.add_argument('--upload', help='Upload data to an assessor')
    parser.add_argument('--upload-type', help='Data type to upload data - if not specified will try to autodetect')
    parser.add_argument('--upload-name', help='Name to give uploaded data - defaults to file basename')
    parser.add_argument('--user', help='XNAT user name. If not specified will use credentials from $HOME.netrc or prompt for username')
    parser.add_argument('--password', help='XNAT password. If not specified will use credentials from $HOME.netrc or prompt for password')
    parser.add_argument('--recurse', action="store_true", help='Recursively list contents of selected object')
    parser.add_argument('--nifti', action="store_true", help='Download NIFTI files in preference to DICOM')
    args = parser.parse_args()

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

        process(connection, args, HIERARCHY[0][0], 0)
        if args.download:
            print("Data downloaded to %s" % args.download)

def process(obj, args, obj_type, hierarchy_idx, indent="", recurse=True):
    print("%s%s: %s" % (indent, obj_type.capitalize(), label(obj)))

    if hierarchy_idx == len(HIERARCHY)-1:
        # At the bottom level, i.e. scan/assessor
        if args.download:
            if args.nifti:
                formats = ['NIFTI', 'DICOM']
            else:
                formats = ['DICOM', 'NIFTI']
            if formats[0] in obj.resources:
                obj.resources[formats[0]].download_dir(args.download)
            elif formats[1] in obj.resources:
                obj.resources[formats[1]].download_dir(args.download)
            else:
                print("WARNING: %s %s does not have any associated DICOM or NIFTI data" % (obj_type.capitalize(), label(obj)))
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
            child_id = getattr(args, child_type)
            if child_id == "skip":
                continue
            elif child_id:
                process(children[child_id], args, child_type, hierarchy_idx+1, indent+"  ", recurse=recurse)
            elif not children:
                print("%s - No %ss found" % (indent, child_type))
            elif recurse:
                for child in children.values():
                    process(child, args, child_type, hierarchy_idx+1, indent+"  ", recurse=args.recurse and not args.download)

if __name__ == '__main__':
    main()
