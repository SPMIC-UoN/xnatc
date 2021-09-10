#!/usr/bin/env python
"""
xnatc - Command line interface to XNAT
"""
import argparse
import sys

import xnat

HIERARCHY = [
    "xnat",
    "project",
    "subject",
    "experiment",
    "scan",
    "",
]

def label(obj):
    if hasattr(obj, "label"):
        return obj.label
    elif hasattr(obj, "xnat_url"):
        return obj.xnat_url
    else:
        return obj.id

def main():
    parser = argparse.ArgumentParser(description='Command line interface to XNAT')
    parser.add_argument('command', default='list', choices=['list', 'get'], help='Command to run: list to list contents, get to get data')
    parser.add_argument('--xnat', default='https://xnatpriv.nottingham.ac.uk/', help='xnat host URL')
    parser.add_argument('--project', help='Project ID')
    parser.add_argument('--subject', help='Subject ID')
    parser.add_argument('--experiment', help='Experiment ID')
    parser.add_argument('--scan', help='Scan ID')
    parser.add_argument('--download-dir', help='Name of download directory', default='xnat_download')
    parser.add_argument('--recurse', action="store_true", help='Recursively list contents of selected object')
    args = parser.parse_args()

    with xnat.connect(args.xnat) as connection:
        connection.xnat_url = args.xnat
        if args.command == "list":
            do_list(connection, 0, args)
        elif args.command == "get":
            if not args.project or not args.subject or not args.experiment:
                check = input("WARNING: download requested for multiple experiment - are you sure? ")
                if check.lower() not in ("y", "yes"):
                    sys.exit(0)

            args.recurse = True
            do_list(connection, 0, args)
        else:
            print("Unknown command: %s" % args.command)
            sys.exit(1)

def do_list(parent, parent_idx, args, indent=""):
    parent_type = HIERARCHY[parent_idx]
    child_type = HIERARCHY[parent_idx+1]

    print("%s%s: %s" % (indent, parent_type.capitalize(), label(parent)))
    if not child_type:
        if args.command == "get":
            parent.resources["DICOM"].download_dir(args.download_dir)
        return

    children = getattr(parent, child_type + "s")
    child_id = getattr(args, child_type)
    if child_id:
        do_list(children[child_id], parent_idx+1, args, indent+"  ")
    elif not children:
        print("%s - No %ss found" % (indent, child_type))
        sys.exit(1)
    elif args.recurse:
        for child in children.values():
            do_list(child, parent_idx+1, args, indent+"  ")
    else:
        for child in children.values():
            print("%s%s: %s" % (indent+"  ", child_type.capitalize(), label(child)))

def do_get(connection, args):
    selected = connection.projects
    if args.project:
        selected = selected[args.project]
        children = selected.subjects
        if args.subject:
            selected = children[args.subject]
            children = selected.experiments
            if args.experiment:
                selected = children[args.experiment]
                children = selected.scans
                if args.scan:
                    selected = children[args.scan]

    print(dir(selected))
    print(selected.resources)
    #selected.download_dir(args.download_dir)

if __name__ == '__main__':
    main()

