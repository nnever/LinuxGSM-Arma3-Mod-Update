#!/usr/bin/python3

import os
import os.path
import sys
import re
import shutil
import getpass
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime
from urllib import request
from argparse import ArgumentParser
from bs4 import BeautifulSoup

#region Configuration
load_dotenv()
parser = ArgumentParser()
parser.add_argument('-u', "--updateall", action="store_true", help="Update game and mods")
parser.add_argument('-ug', "--updategame", action="store_true", help="Only update mods")
parser.add_argument('-um', "--updatemods", action="store_true", help="Only update game")
parser.add_argument('-s', "--startserver", action="store_true", help="Run server")

A3_SERVER_ID = "233780"
A3_WORKSHOP_ID = "107410"
STEAM_CMD = Path(Path.cwd(), "Steam/steamcmd.sh")
A3_GAME_INSTALL_DIR = Path(Path.cwd(), "arma3/install/")
A3_SERVER_DIR = Path(Path.cwd(), "arma3/install/public")
A3_WORKSHOP_DIR = Path(Path.cwd(),"arma3/install/public/steamapps/workshop/content/", A3_WORKSHOP_ID)
A3_MODS_DIR = Path(A3_SERVER_DIR, "mods")
A3_SERVER_CFG = Path(A3_SERVER_DIR, "serverconfig/server.cfg")
A3_SERVER_BASIC_CFG = Path(A3_SERVER_DIR, "serverconfig/basic.cfg")

LAUNCH_PARAMETERS = (
    f"-cfg=\"{A3_SERVER_BASIC_CFG}\" "
    f"-config=\"{A3_SERVER_CFG}\" "
    f"-name=\"public\" "
    f"-world=empty "
    f"-port=2302 "
    f"-noSound"
)

#endregion

#region Functions
def log(msg: str):
    print("")
    print(f"{'=' * len(msg)}")
    print(msg)
    print(f"{'=' * len(msg)}")

def call_steamcmd(params: str):
    os.system(f"{STEAM_CMD} {params}")
    print("")

def find_modlist_html_file() -> Path:
    modlists_dir = Path(A3_SERVER_DIR, "modlists")
    if not modlists_dir.exists():
        print(f"Modlist directory does not exist: {modlists_dir}")
        sys.exit()

    print("Select one of the following modlists:")
    file_list = sorted(modlists_dir.iterdir())

    if not file_list:
        print("No modlist html files found.")
        sys.exit()

    for idx, file in enumerate(file_list, start=1):
        print(f"{idx}.) {file.name}")

    print("")
    try:
        if len(file_list) == 1:
            selected_file_idx = 0
        else:
            selected_file_idx = int(input("Enter Number: ")) - 1
        mod_file = file_list[selected_file_idx]
    except (ValueError, IndexError):
        print("Invalid selection.")
        sys.exit()

    if mod_file.suffix != ".html":
        print(f"{mod_file} is not an HTML file.")
        sys.exit()

    return mod_file

def extract_modlist_from_html(modlist_file: Path) -> dict:
    with open(modlist_file, "r", encoding="utf-8") as file:
        soup = BeautifulSoup(file.read(), features="lxml")

    mods = {}
    for item in soup.findAll("tr", {"data-type" : "ModContainer"}):
        name_link   = item.find("a", {"data-type" : "Link"})
        name_object = item.find("td", {"data-type" : "DisplayName"})

        workshop_id = re.search(r"id=(\d+)", name_link["href"])

        if workshop_id:
            mod_id = workshop_id.group(1)
            mod_link = name_object.contents[0].lower().replace(" ", "_")
            mods[f"@{mod_link}"] = mod_id
    return mods

def mod_needs_update(mod_id: str, path: Path) -> bool:
    if path.exists():
        workshop_changelog_url = "https://steamcommunity.com/sharedfiles/filedetails/changelog"
        update_pattern = re.compile(r"workshopAnnouncement.*?<p id=\"(\d+)\">", re.DOTALL)
        response = request.urlopen(f"{workshop_changelog_url}/{mod_id}").read()
        response = response.decode("utf-8")
        match = update_pattern.search(response)

        if match:
            updated_at = datetime.fromtimestamp(int(match.group(1)))
            created_at = datetime.fromtimestamp(os.path.getctime(path))

            return updated_at >= created_at

    return False

def get_mod_update_list(mods_to_check: dict) -> dict:
    log("Checking for missing mods")
    outdated_mods = {}
    for mod_name, mod_id in mods_to_check.items():
        mod_path = Path(A3_WORKSHOP_DIR, mod_id)
        if mod_path.exists():
            if mod_needs_update(mod_id, mod_path):
                print(f"Update required for \"{mod_name}\" ({mod_id})")
                shutil.rmtree(mod_path)
            else:
                print(f"No update required for \"{mod_name}\" ({mod_id})... SKIPPING")
                continue
        outdated_mods[mod_name] = mod_id
    print(outdated_mods)
    return outdated_mods

def update_mods(mods: dict, username: str, password: str) -> None:
    log("Updating mods")
    steam_cmd_params  = f" +force_install_dir {A3_SERVER_DIR} +login \"{username}\" \"{password}\""
    for mod_name, mod_id in mods.items():
        steam_cmd_params += f" +workshop_download_item {A3_WORKSHOP_ID} {mod_id} validate"
        print(f"Updating \"{mod_name}\" ({mod_id})")
    call_steamcmd(f"{steam_cmd_params}  +quit")

def lowercase_workshop_dir() -> None:
    log("Converting uppercase files/folders to lowercase...")
    def rename_all( root, items):
        for name in items:
            try:
                os.rename(os.path.join(root, name),
                os.path.join(root, name.lower()))
            except OSError:
                pass # can't rename it, so what

    # starts from the bottom so paths further up remain valid after renaming
    for root, dirs, files in os.walk(A3_WORKSHOP_DIR, topdown=False):
        rename_all(root, dirs)
        rename_all(root, files)


def delete_old_symlinks():
    log("Deleting old symlinks...")
    for entry in os.listdir(A3_MODS_DIR):
        entry_path = os.path.join(A3_MODS_DIR, entry)
        if os.path.islink(entry_path):
            os.unlink(entry_path)
            print(f"Deleted old symlink '{entry_path}'...")

def create_mod_symlinks(mods: dict) -> None:
    log("Creating symlinks...")
    for mod_name, mod_id in mods.items():
        link_path = f"{A3_MODS_DIR}/{mod_name}"
        real_path = f"{A3_WORKSHOP_DIR}/{mod_id}"

        if os.path.isdir(real_path):
            if not os.path.islink(link_path):
                os.symlink(real_path, link_path)
                print(f"Creating symlink '{link_path}'...")
        else:
            print(f"Mod '{mod_name}' does not exist! ({real_path})")

def update_server(username: str, password: str) -> None:
    log(f"Updating A3 server ({A3_SERVER_ID})")
    update_command = (
        f"+force_install_dir {A3_GAME_INSTALL_DIR} "
        f"+login \"{username}\" \"{password}\" "
        f"+app_update 233780 validate "
        f"+quit"
        )
    call_steamcmd(update_command)

def generate_cfg(mods: dict) -> None:
    log("Generating config file...")
    config_mods = ""
    for mod_name in mods.keys():
        config_mods += fr"mods/{re.escape(mod_name)};"

    config_mods = f"mods=\"{config_mods}\";"

    with open(A3_SERVER_CFG, "r+", encoding="utf-8") as config_file:
        lines = config_file.readlines()

    replaced = False

    for i, line in enumerate(lines):
        if re.search(r'mods\=".*\"', line):
            if lines[i].strip() != '':
                lines[i] = f"{config_mods}"
            else:
                lines[i] = f"{config_mods}"
            replaced = True
            break

    if not replaced:
        if lines and lines[-1].strip():
            lines.append(f"\n{config_mods}\n")
        else:
            lines.append(f"{config_mods}")

    with open(A3_SERVER_CFG, "w", encoding="utf-8") as config_file:
        config_file.writelines(lines)

def start_server(params):
    log("Start A3 server")
    os.system(f"cd {A3_SERVER_DIR} && ./arma3server {params}")

def get_credentials() -> tuple[str, str]:
    print("A steam account owning arma3 is required to continue. Please log in to begin downloading.")
    username = os.getenv('STEAM_USERNAME')
    password = os.getenv('STEAM_PASSWORD')
    if not username or not password:
        username = input("Steam Username: ")
        password = getpass.getpass(prompt="Steam Password ")
    return username, password

#endregion

if __name__ == "__main__":

    args = parser.parse_args()
    START_SERVER = args.startserver
    UPDATE_ALL = args.updateall

    if UPDATE_ALL:
        UPDATE_A3 = True
        UPDATE_MODS = True
    else:
        UPDATE_A3 = args.updategame
        UPDATE_MODS = args.updatemods

    if UPDATE_A3:
        steam_user, steam_pass = get_credentials()
        update_server(steam_user, steam_pass)

    if UPDATE_MODS:
        html_modlist = find_modlist_html_file()
        mod_list = extract_modlist_from_html(html_modlist)
        mods_to_update = get_mod_update_list(mod_list)

        if mods_to_update:
            steam_user, steam_pass = get_credentials()
            update_mods(mods_to_update, steam_user, steam_pass)
        else:
            print("All mods are up to-date")

        lowercase_workshop_dir()
        delete_old_symlinks()
        create_mod_symlinks(mod_list)
        generate_cfg(mod_list)

    if START_SERVER:
        start_server(LAUNCH_PARAMETERS)
