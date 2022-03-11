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

def main():
    parser = argparse.ArgumentParser(description='Migrate XNAT project storage from local folder to R drive')
    parser.add_argument('--xnat-archive', help='xnat archive folder')
    parser.add_argument('--project', help='Project ID')
    parser.add_argument('--rdrive-folder', help='R drive archive folder')
    parser.add_argument('--no-backup', help='Do not create backup of XNAT project', action="store_true", default=False)
    parser.add_argument('--remove-backup', help='Remove backup of XNAT project on success', action="store_true", default=False)
    
    args = parser.parse_args()

    # Check XNAT archive exists and project is found

    # Check R drive folder exists with appropriate permissions

    # Calculate storage requirements and confirm change

    # Back up XNAT project
    if not args.no_backup:
        pass

    # Copy XNAT project to R drive folder

    # Remove existing folder

    # Create link to R drive folder

    # Create placeholder files (README.txt and DO_NOT_MODIFY_THIS_FOLDER.txt)

    # Remove backup if required
    if args.remove_backup:
        pass

if __name__ == '__main__':
    main()
