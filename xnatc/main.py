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
from urllib.parse import urlparse

import pyxnat

from . import bids

def get_auth(args):
    if args.user and args.password:
        return
    if '//' not in args.xnat:
        print("WARNING: Xnat host did not have HTTP or HTTPS specified - assuming HTTPS")
        args.xnat = 'https://' + args.xnat
    url = urlparse(args.xnat)
    try:
        auth_data = netrc.netrc()
        if url.hostname in auth_data.hosts:
            args.user, _account, args.password = auth_data.authenticators(url.hostname)
    except:
        pass # fixme

    if not args.user or not args.password:
        print("WARNING: No authentication information found in $HOME/.netrc")
        if not args.user:
           args.user = input("Username: ").strip()
        if not args.password:
            args.password = getpass.getpass()
        print("  Note: You can add your credentials to $HOME/.netrc for automatic login")
        print("        See https://xnat.readthedocs.io/en/latest/static/tutorial.html#credentials")

def main():
    parser = argparse.ArgumentParser(description='Command line interface to XNAT')
    g = parser.add_argument_group("XNAT connection")
    g.add_argument('--xnat', default='https://xnatpriv.nottingham.ac.uk/', help='xnat host URL')
    g.add_argument('--user', help='XNAT user name. If not specified will use credentials from $HOME.netrc or prompt for username')
    g.add_argument('--password', help='XNAT password. If not specified will use credentials from $HOME.netrc or prompt for password')
    g = parser.add_argument_group("Data selection")
    g.add_argument('--project', help='Project name/ID')
    g.add_argument('--subject', help='Subject name/ID')
    g.add_argument('--experiment', '--session', help='Experiment/Session name/ID')
    g.add_argument('--scan', help='Scan ID')
    g.add_argument('--assessor', help='Assessor name/ID')
    g.add_argument('--match-type', help='Type of matching for project specifications etc', choices=['glob', 're'], default='glob')
    g.add_argument('--match-files', action="store_true", help='Allow subject/experiment/scan etc to be file names containing ID lists')
    g = parser.add_argument_group("Downloading data")
    g.add_argument('--download', help='Download data to named directory')
    g.add_argument('--download-resource', help='Name of resource type to download', default='DICOM')
    g.add_argument('--download-format', help='Download format', default="xnat", choices=["xnat", "bids"])
    #g.add_argument('--bids-mapper', help='BIDS mapper', default="default")
    g = parser.add_argument_group("Uploading data")
    g.add_argument('--upload', help='File or directory containing data to upload to a scan/assessor')
    g.add_argument('--upload-resource', help='Resource type for uploaded data - if not specified will try to autodetect from file type')
    g.add_argument('--upload-name', help='Name to give uploaded data - defaults to file basename')
    g.add_argument('--create-assessor', help='File containing XML definition of assessor to create')
    parser.add_argument('--debug', action="store_true", help='Enable debug mode')
    args = parser.parse_args()
    args.list_children = True

    get_auth(args)

    connection = pyxnat.Interface(server=args.xnat, user=args.user, password=args.password, verify=False)
    connection.xnat_url = args.xnat

    if args.download:
        if args.download_format == "bids" and not args.download_resource == "NIFTI":
            print("WARNING: Setting download resource to NIFTI as required for BIDS")
            args.download_resource = "NIFTI"

        if args.download_format == "bids":
            do_list(connection, args, action=bids.download_bids)
        elif args.download_format == "xnat":
            do_list(connection, args, action=download_obj)
        else:
            print("Unknown download format: %s" % args.download_format)
            sys.exit(1)

        print("Data downloaded to %s" % args.download)

    elif args.upload:
        if not args.project or not args.subject or not args.experiment or not (args.scan or args.assessor):
            raise RuntimeError("To upload data you must fully specify a project, subject, experiment and either a scan or an assessor")
        do_upload(connection, args)

    elif args.create_assessor:
        if not args.project or not args.subject:
            raise RuntimeError("To create an assessor you must specify a project and subject (optionally an experiment too)")
        do_create_assessor(connection, args)

    else:
        do_list(connection, args)

def do_create_assessor(conn, args):
    res = find(conn, args)
    if not res:
        print("Could not find unique matching object to create assessor for")
        return False
    
    obj, obj_type, path = res
    print("Uploading %s as an assessor for %s: %s" % (args.create_assessor, obj_type, obj.label()))
    with open(args.create_assessor, "r") as f:
        path="/data/" + path + "/assessors/"
        r = conn.post(path, files={"file" : f})
        if r.status_code != 200:
            raise RuntimeError("Failed to upload assessor: %i" % r.status_code)

    return True

def do_upload(conn, args):
    res = find(conn, args)
    if not res:
        print("Could not find unique matching object to upload file for")
        return False

    obj, obj_type, path = res
    if os.path.isdir(args.upload):
        print("Uploading contents of %s as resource for %s: %s" % (args.upload,obj_type, obj.label()))
        for fname in os.listdir(args.upload):
            fpath = os.path.join(args.upload, fname)
            if os.path.isdir(fpath):
                for sub_fname in os.listdir(fpath):
                    sub_fpath = os.path.join(fpath, sub_fname)
                    upload_file(obj, fname, sub_fpath)
            else:
                upload_file(obj, args.upload_resource, fpath)
    else:
        print("Uploading %s as %s resource for %s: %s" % (args.upload, args.upload_resource, obj_type, obj.label()))
        upload_file(obj, args.upload_resource, args.upload, args.upload_name)

    return True

def upload_file(obj, resource_type, fname, upload_name=None):
    if not upload_name:
        upload_name = os.path.basename(fname)
    if not resource_type and (fname.lower().endswith(".nii") or fname.lower().endswith(".nii.gz")):
        resource_type = 'NIFTI'

    if resource_type:
        r = obj.resource(resource_type)
        r.file(upload_name).put(fname)
    else:
        print("WARNING: Could not detect resource type for %s - will not upload" % fname)

def find(conn, args):
    """
    Find a specific object based on args passed
    """
    path=""
    projects = conn.select.projects()
    found = False
    for p in projects:
        if exact_match(p, args.project):
            path += "projects/" + p.id()
            found = True
            break
    if not found:
        return
    elif not args.subject:
        return p, "project", path

    found = False
    for s in p.subjects():
        if exact_match(s, args.subject):
            path += "/subjects/" + s.id()
            found = True
            break
    if not found:
        return
    elif not args.experiment:
        return s, "subject", path

    found = False
    for e in s.experiments():
        if exact_match(e, args.experiment):
            path += "/experiments/" + e.id()
            found = True
            break
    if not found:
        return
    elif not args.scan and not args.assessor:
        return e, "experiment", path

    found = False
    if args.scan:
        for s in e.scans():
            if exact_match(s, args.scan):
                path += "/scans/" + s.id()
                found = True
                s_type = "scan"
                break
    elif args.assessor:
        for s in e.assessors():
            if exact_match(s, args.assessor):
                path += "/assessors/" + s.id()
                found = True
                s_type = "assessor"
                break
    if not found:
        return
    else:
        return s, s_type, path

def download_bids(obj, obj_type, args, path):
    if obj_type != "scan":
        return
        
    r = obj.resource(args.download_resource)
    proj = obj.project().label()
    subj = obj.subject().label()
    exp = obj.experiment().label()
    
    for idx, f in enumerate(r.files()):
        if idx == 0:
            print("Downloading files for %s: %s" % (obj_type, obj.label()))
        f.get(os.path.join(download_path, f.label()))
                 
def download_obj(obj, obj_type, args, path):
    download_path = os.path.join(args.download, path, args.download_resource)
    os.makedirs(download_path, exist_ok=True)
    r = obj.resource(args.download_resource)

    for idx, f in enumerate(r.files()):
        if idx == 0:
            print("Downloading files for %s: %s" % (obj_type, obj.label()))
        f.get(os.path.join(download_path, f.label()))
                         
def print_obj(obj, obj_type, args, path):
    prefixes = {
        "project" : "", "subject" :  " - ", "experiment" : "  - ", "scan" : "   - ", "assessor" : "   - ",
    }
    print("%s%s: %s" % (prefixes[obj_type.lower()], obj_type, obj.label()))

def do_list(conn, args, path="projects/", action=print_obj):
    """
    List matching projects, subject etc
    """
    projects = conn.select.projects()
    for p in projects:
        if matches(p, args.project, args):
            ppath = path + p.label()
            action(p, "project", args, ppath)
            do_list_subjects(p, args, ppath + "/subjects/" , action)

def do_list_subjects(proj, args, path, action):
    subjects = proj.subjects()
    for s in subjects:
        if matches(s, args.subject, args):
            opath = path + s.label()
            action(s, "subject", args, opath)
            do_list_experiments(s, args, opath + "/experiments/", action)

def do_list_experiments(subj, args, path, action):
    exps = subj.experiments()
    for e in exps:
        if matches(e, args.experiment, args):
            opath = path + e.label()
            action(e, "session", args, opath)
            do_list_scans(e, args, opath + "/scans/", action)
            do_list_assessors(e, args, opath + "/assessors/", action)

def do_list_scans(exp, args, path, action):
    scans = exp.scans()
    for s in scans:
        if matches(s, args.scan, args):
            opath = path + s.label()
            action(s, "scan", args, opath)

def do_list_assessors(exp, args, path, action):
    assessors = exp.assessors()
    for a in assessors:
        if matches(a, args.assessor, args):
            opath = path + a.label()
            action(a, "assessor", args, opath)

def exact_match(obj, match_id):
    return obj.label().lower() == match_id.lower() or obj.id().lower() == match_id.lower()

def matches(obj, match_id, args):
    if match_id == "skip":
        return False
    elif not match_id:
        return True

    if args.match_files and os.path.exists(match_id):
        with open(match_id) as f:
            match_ids = [l.strip() for l in f.readlines()]
    else:
        match_ids = [match_id]

    for match_id in match_ids:
        if args.match_type == "glob":
            match_id = fnmatch.translate(match_id)

        p = re.compile(match_id, re.IGNORECASE)
        if p.match(obj.id()):
            return True
        elif p.match(obj.label()):
            return True

    return False

if __name__ == '__main__':
    main()
