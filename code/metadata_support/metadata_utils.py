import pandas as pd

import os
from pathlib import Path
from xml.dom import minidom

from project_config import SESSIONS_DIR

BASE_DIR = str(SESSIONS_DIR)
RECORD_NODE = os.path.join("ecephys", "Record Node 101")

def add_seconds_to_clock(sec, clock):
    """This function accepts any integer number of seconds (sec) and adds them to a 24-hour format time string (clock)\
    
    It will fail if the final answer should roll the clock over midnight"""

    clock_s = int(clock[-2:])
    clock_m = int(clock[-5:-3])
    clock_h = int(clock[-8:-6])

    converted_sum = (clock_h * 3600) + (clock_m * 60) + clock_s + sec

    hours = str(converted_sum // 3600)
    mins = str((converted_sum % 3600) // 60)
    secs = str(((converted_sum % 3600) % 60))

    while len(hours) < 2:
        hours = "0" + str(hours)
    while len(mins) < 2:
        mins = "0" + str(mins)
    while len(secs) < 2:
        secs = "0" + str(secs)

    return str(hours) + ":" + str(mins) + ":" + str(secs)

# FILE HANDLING

#FILE OPENING

def csv_opener(filepath):
    """Accepts file name and path as string and returns a dictionary"""

    data = pd.read_csv(filepath)
    return data.to_dict()

def get_insertion_details(csv_opener_output, setup_number):
    """Accepts an insertion or target dict (csv_opener output) & setup number and returns a dictionary where
    the keys are the column headings and the values are the appropriate data for that setup
    """

    new_dict = {}
    setup_index = None
    setup_number = int(setup_number)

    for i, j in csv_opener_output["Setup No"].items():
        try:
            if int(j) == setup_number:
                setup_index = i
        except:
            continue
        
    assert setup_index is not None, "Setup number not found"
    for i in csv_opener_output.keys():
        new_dict[i] = csv_opener_output[i][setup_index]
    return new_dict

def xl_opener(filepath):
    """
    Turns an Excel spreadsheet into interpretable dicts
    
    Parameters
    ----------
    filename : str
                path of the .xlx file
    
    Returns
    -------
    Dictionary of dictionaries
    More specifically, of the form {sheet_index (int): dict}
    Where dict is of the form {column heading (str): list of values}
    """

    sheet_data = {}
    data = pd.ExcelFile(filepath)

    for sheet_index in range(len(data.sheet_names)):
        sheet_data[sheet_index] = (pd.read_excel(data, sheet_name=sheet_index)).to_dict()
    return sheet_data

def find_session_folder(target_names, all_sessions):
    """Return the first session folder whose name contains any of the target names."""
    for name in target_names:
        for session in all_sessions:
            if name in session:
                return session
    return None


def load_xml(path):
    """Parse XML if it exists, otherwise return None."""
    if not os.path.exists(path):
        return None
    return minidom.parse(path)


def xml_opener(target_dict_list):
    """
    Returns:
        {
            "recording": <XML from experiment1/settings.xml>,
            "surface_finding": <XML from experiment2/settings_2.xml>
        }
    """

    xml_bank = {"recording": None, "surface_finding": None}

    # Collect all session folders once
    all_sessions = os.listdir(BASE_DIR)

    # --- Identify session folder ---
    recording_targets = {str(t["OEPh Recording"]) for t in target_dict_list}
    session_folder = find_session_folder(recording_targets, all_sessions)

    if session_folder is None:
        return xml_bank  # nothing found

    session_path = os.path.join(BASE_DIR, session_folder, RECORD_NODE)
    
    # --- Explicit mapping ---
    exp1_xml = os.path.join(session_path, "settings.xml")
    exp2_xml = os.path.join(session_path, "settings_2.xml")
    print(f"Looking for XML files in {exp1_xml}...")
    # Load them
    xml_bank["recording"] = load_xml(exp1_xml)
    xml_bank["surface_finding"] = load_xml(exp2_xml)

    return xml_bank

# FILE PARSING

def xml_attribute(xml, tag_name, index, attribute):
    """This function takes the following inputs:
    xml: an opened xml document object as input (use the output of xml_opener)
    tag_name: a tag name (e.g. NP_PROBE) as a string
    index: the integer index of the tag; index = 0 if you are trying to find the first probe (NP_PROBE) in the xml
    attribute: a desired attribute (e.g. probe_serial_number) as a string, whose value will be returned as an output
    """

    return (xml.getElementsByTagName(tag_name)[index]).getAttribute(attribute)
