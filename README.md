# Sigenergy Smart Port Integration for Home Assistant

A custom Home Assistant integration that provides full control over your **Sigenergy Smart Port**, allowing you to toggle manual load switching and seamlessly transition between Manual control and native Auto (Sig Schedule) modes.

## Why This Integration Exists

The official Sigenergy OpenAPI restricts or completely locks out remote control commands for Smart Port relays for regular consumer tiers. This custom integration bypasses those cloud restrictions by reverse-engineering and securely mimicking the exact `PATCH` request sequences used by the official **mySigen Web App** ecosystem (hosted on `api-aus.sigencloud.com`).

---

## Features

- **Power Relay Switch (`switch.sigen_smart_port_control`)**: Instantly turn your smart port loads (e.g., EV Chargers, Hot Water systems) On or Off manually.
- **Mode Dropdown Selector (`select.sigen_smart_port_mode`)**: A clean UI dropdown to instantly cycle between **Manual** and **Auto (Sig Schedule)** modes.
- **Automated Token Management**: Automatically handles login session handshake wrappers behind the scenes every time an action is taken.

---

## File Structure

To install this component, place the integration files into your Home Assistant directory matching this exact path structure:

```text
config/
└── custom_components/
    └── sigen_smartport/
        ├── __init__.py
        ├── manifest.json
        ├── select.py
        └── switch.py
		
		
##🚀 Installation & Setup
Follow these exact steps to add the integration files, acquire your credentials from the web app, and activate the entities.

##Step 1: Install the Component Files
Access your Home Assistant file system (using Samba, SSH, VS Code Server, or the File Editor add-on).

Inside your main config directory, look for a folder named custom_components (if it does not exist, create it).

Create a new directory inside it named exactly sigen_smartport.

Drop the __init__.py, manifest.json, switch.py, and select.py files from this repository directly into that folder.

##Step 2: Retrieve Your Encrypted Password & Station ID
Because this integration interacts directly with the private app cloud endpoints, you need to capture the exact login string your web profile sends out.

Using a desktop web browser (Chrome or Edge), go to your region's login page (e.g., https://app-aus.sigencloud.com or equivalent).

Right-click anywhere on the page and select Inspect to open Developer Tools, then click on the Network tab.

In the Filter box, type /token to narrow the logs down.

Log into your account using your regular mySigen app username and password.

In the network panel list, click on the token network request row that shows up and navigate to its Payload or Body tab.

Copy down your hardware parameters:

username: Your account email.

password: Copy the entire raw, encrypted Base64 string that follows password= (it will look like 2345fdfwregt323r==).

station_id: Your 15-digit inverter station string (e.g., 1034555545453).

Step 3: Configure configuration.yaml
Open your main configuration.yaml file and add the configuration blocks for both the switch and select platforms. Supply your captured credentials:		

Step 4: Validate and Restart Home Assistant
Because this component introduces a brand new domain architecture (select.py), Home Assistant must perform a clean boot to register the backend components.

In your Home Assistant UI, navigate to Settings > Developer Tools > YAML.

Click Check Configuration to ensure your spacing and strings are syntactically sound.

Click Restart to perform a system restart.
