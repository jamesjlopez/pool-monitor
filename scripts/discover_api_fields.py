#!/usr/bin/env python3
"""
discover_api_fields.py — authenticate with Pentair cloud and dump the full
API response so we can identify which fields carry RPM, watts, and GPH.

Usage:
    python scripts/discover_api_fields.py
    # prompts for email + password (not stored anywhere)

Output: logs/api_response_dump.json with the full raw response.
"""

import getpass
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import boto3
import requests
from pycognito import Cognito
from requests_aws4auth import AWS4Auth

# Pentair AWS Cognito config (from pentair_cloud HA integration, publicly reverse-engineered)
AWS_REGION          = "us-west-2"
AWS_USER_POOL_ID    = "us-west-2_lbiduhSwD"
AWS_CLIENT_ID       = "3de110o697faq7avdchtf07h4v"
AWS_IDENTITY_POOL_ID = "us-west-2:6f950f85-af44-43d9-b690-a431f753e9aa"
AWS_COGNITO_ENDPOINT = "cognito-idp.us-west-2.amazonaws.com"

PENTAIR_BASE        = "https://api.pentair.cloud"
DEVICES_PATH        = "/device/device-service/user/devices"
DEVICE_STATUS_PATH  = "/device2/device2-service/user/device"

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


def authenticate(email: str, password: str):
    print("Authenticating with Pentair cloud...")
    u = Cognito(AWS_USER_POOL_ID, AWS_CLIENT_ID, username=email)
    u.authenticate(password=password)
    id_token = u.id_token
    print("  Auth OK — got Cognito ID token")
    return id_token


def get_aws_credentials(id_token: str):
    print("Exchanging Cognito token for AWS credentials...")
    client = boto3.client("cognito-identity", region_name=AWS_REGION)
    logins = {f"{AWS_COGNITO_ENDPOINT}/{AWS_USER_POOL_ID}": id_token}

    identity = client.get_id(IdentityPoolId=AWS_IDENTITY_POOL_ID, Logins=logins)
    identity_id = identity["IdentityId"]

    creds = client.get_credentials_for_identity(IdentityId=identity_id, Logins=logins)
    c = creds["Credentials"]
    print("  Got AWS temporary credentials")
    return c["AccessKeyId"], c["SecretKey"], c["SessionToken"]


def get_auth(access_key, secret_key, session_token):
    return AWS4Auth(access_key, secret_key, AWS_REGION, "execute-api",
                    session_token=session_token)


def get_headers(id_token: str) -> dict:
    return {
        "x-amz-id-token": id_token,
        "user-agent": "aws-amplify/4.3.10 react-native",
        "content-type": "application/json; charset=UTF-8",
    }


def list_devices(auth, headers) -> list:
    print("\nFetching device list...")
    r = requests.get(PENTAIR_BASE + DEVICES_PATH, auth=auth, headers=headers, timeout=15)
    r.raise_for_status()
    data = r.json()
    print("  Raw device list response:")
    print(json.dumps(data, indent=2))
    return data.get("data", [])


def get_device_status(auth, headers, device_ids: list) -> dict:
    print("\nFetching device status (full raw response)...")
    payload = json.dumps({"deviceIds": device_ids})
    r = requests.post(PENTAIR_BASE + DEVICE_STATUS_PATH, auth=auth,
                      headers=headers, data=payload, timeout=15)
    r.raise_for_status()
    return r.json()


def main():
    print("Pentair Cloud API Field Discovery")
    print("=" * 50)
    print("This script will authenticate with your Pentair Home account")
    print("and dump the full API response to find RPM/watts/GPH fields.")
    print("Credentials are used only for this session — not stored.\n")

    email = input("Pentair Home email: ").strip()
    password = getpass.getpass("Pentair Home password: ")

    try:
        id_token = authenticate(email, password)
        access_key, secret_key, session_token = get_aws_credentials(id_token)
        auth = get_auth(access_key, secret_key, session_token)
        headers = get_headers(id_token)

        devices = list_devices(auth, headers)
        if not devices:
            print("\nNo devices found in your account.")
            sys.exit(1)

        print(f"\nFound {len(devices)} device(s):")
        for d in devices:
            print(f"  {d.get('deviceId')}  type={d.get('deviceType')}  "
                  f"status={d.get('status')}  name={d.get('productInfo', {}).get('nickName', '?')}")

        device_ids = [d["deviceId"] for d in devices]
        status = get_device_status(auth, headers, device_ids)

        # Save full dump
        out = LOG_DIR / "api_response_dump.json"
        with open(out, "w") as f:
            json.dump({"devices": devices, "status": status}, f, indent=2)
        print(f"\nFull response saved to {out}")

        # Print all field keys from the status response so we can find RPM/watts/GPH
        print("\n--- ALL FIELD KEYS IN STATUS RESPONSE ---")
        try:
            for device_data in status["response"]["data"]:
                print(f"\nDevice: {device_data['deviceId']}")
                fields = device_data.get("fields", {})
                for key, val in sorted(fields.items()):
                    v = val.get("value", "") if isinstance(val, dict) else val
                    print(f"  {key:20s} = {v}")
        except (KeyError, TypeError) as e:
            print(f"Unexpected response structure: {e}")
            print("Full status response:")
            print(json.dumps(status, indent=2))

    except Exception as e:
        print(f"\nError: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
