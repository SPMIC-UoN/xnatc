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
    parser.add_argument('--xnat', default='https://xnatpriv.nottingham.ac.uk/', help='xnat host URL')
    parser.add_argument('--project', help='Project ID')
    parser.add_argument('--subject', help='Subject ID')
    parser.add_argument('--experiment', help='Experiment ID')
    parser.add_argument('--scan', help='Scan ID')
    parser.add_argument('--download', help='Download data to named directory')
    parser.add_argument('--recurse', action="store_true", help='List contents of selected object')
    args = parser.parse_args()

    with xnat.connect(args.xnat) as connection:
        connection.xnat_url = args.xnat
        if args.download and not (args.project and args.subject and args.experiment):
            check = input("WARNING: download requested for multiple experiment - are you sure? ")
            if check.lower() not in ("y", "yes"):
                sys.exit(0)

        process(connection, args, 0)

def process(obj, args, hierarchy_idx, indent="", recurse=True):
    obj_type = HIERARCHY[hierarchy_idx]
    print("%s%s: %s" % (indent, obj_type.capitalize(), label(obj)))

    if hierarchy_idx == len(HIERARCHY)-1:
        # At the bottom level, i.e. scan
        if args.download:
            if 'DICOM' in obj.resources:
                obj.resources["DICOM"].download_dir(args.download)
            else:
                print("WARNING: Scan %s does not have any associated DICOM data" % label(obj))
    else:
        child_type = HIERARCHY[hierarchy_idx+1]
        children = getattr(obj, child_type + "s")
        child_id = getattr(args, child_type)
        if child_id:
            process(children[child_id], args, hierarchy_idx+1, indent+"  ", recurse=recurse)
        elif not children:
            print("%s - No %ss found" % (indent, child_type))
        elif recurse:
            for child in children.values():
                process(child, args, hierarchy_idx+1, indent+"  ", recurse=args.recurse and not args.download)

if __name__ == '__main__':
    main()
