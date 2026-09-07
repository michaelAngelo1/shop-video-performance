import os
import json
import time
import hmac
import hashlib
import requests
from google.cloud import secretmanager
from dotenv import load_dotenv

load_dotenv()

secret_client = secretmanager.SecretManagerServiceClient()

BRANDS_INTERNAL_APP = {
    "Eileen Grace": 1,
    "Mamaway": 1,
    "SHRD": 1,
    "Miss Daisy": 1,
    "Polynia": 1,
    "CHESS": 1,
    "Cléviant": 1,
    "Mossèru": 1,
    "Evoke": 1,
    "Dr Jou": 1,
    "Mirae": 2,
    "Swissvita": 2,
    "G-Belle": 2,
    "Past Nine": 2,
    "Nutri & Beyond": 2,
    "Ivy & Lily": 2,
    "Naruko": 2,
    "Relove": 2,
    "Joey & Roo": 2, 
    "Rocketindo Shop": 2,
    "M2": 3,
}

TIKTOK_SECRETS = {
    "Eileen Grace": "projects/231801348950/secrets/eg-tiktok-tokens",
    "Mamaway": "projects/231801348950/secrets/mamaway-tiktok-tokens",
    "SHRD": "projects/231801348950/secrets/shrd-tiktok-tokens",
    "Miss Daisy": "projects/231801348950/secrets/md-tiktok-tokens",
    "Polynia": "projects/231801348950/secrets/polynia-tiktok-tokens",
    "CHESS": "projects/231801348950/secrets/chess-tiktok-tokens",
    "Cléviant": "projects/231801348950/secrets/cleviant-tiktok-tokens",
    "Mossèru": "projects/231801348950/secrets/mosseru-tiktok-tokens",
    "Evoke": "projects/231801348950/secrets/evoke-tiktok-tokens",
    "Dr Jou": "projects/231801348950/secrets/drjou-tiktok-tokens",
    "Mirae": "projects/231801348950/secrets/mirae-tiktok-tokens",
    "Swissvita": "projects/231801348950/secrets/swissvita-tiktok-tokens",
    "G-Belle": "projects/231801348950/secrets/gbelle-tiktok-tokens",
    "Past Nine": "projects/231801348950/secrets/pn-tiktok-tokens",
    "Nutri & Beyond": "projects/231801348950/secrets/nb-tiktok-tokens",
    "Ivy & Lily": "projects/231801348950/secrets/il-tiktok-tokens",
    "Naruko": "projects/231801348950/secrets/naruko-tiktok-tokens",
    "Relove": "projects/231801348950/secrets/relove-tiktok-tokens",
    "Joey & Roo": "projects/231801348950/secrets/joey-roo-tiktok-tokens",
    "Rocketindo Shop": "projects/231801348950/secrets/rocketindo-shop-tiktok-tokens",
    "M2": "projects/231801348950/secrets/m2-tiktok-tokens"
}

def get_app_credentials(brand: str):
    """Helper to fetch appKey and appSecret based on brand grouping."""
    app_id = BRANDS_INTERNAL_APP.get(brand)
    if app_id == 1:
        return os.getenv('INTERNAL_APP_KEY'), os.getenv('INTERNAL_APP_SECRET')
    elif app_id == 2:
        return os.getenv('SECOND_INTERNAL_APP_KEY'), os.getenv('SECOND_INTERNAL_APP_SECRET')
    else:
        return os.getenv('THIRD_INTERNAL_APP_KEY'), os.getenv('THIRD_INTERNAL_APP_SECRET')


def load_tokens(brand: str):
    secret_name = f"{TIKTOK_SECRETS[brand]}/versions/latest"
    print(f"Secret name on: {brand} : {secret_name}")
    try:
        response = secret_client.access_secret_version(request={"name": secret_name})
        payload = response.payload.data.decode("UTF-8")
        tokens = json.loads(payload)
        # print(f"[TIKTOK-SECRETS] Tokens loaded: {tokens}")
        return tokens
    except Exception as e:
        print(f"[TIKTOK-SECRETS] Error loading tokens for brand: {brand}")
        print(e)
        return None


def save_tokens(brand: str, tokens: dict):
    parent = TIKTOK_SECRETS[brand]
    payload_bytes = json.dumps(tokens, indent=2).encode("UTF-8")

    try:
        new_version = secret_client.add_secret_version(
            request={
                "parent": parent,
                "payload": {"data": payload_bytes},
            }
        )
        print(f"Saved Tiktok Tokens to Secret Manager on brand: {brand}")

        versions = secret_client.list_secret_versions(request={"parent": parent})
        
        for version in versions:
            if version.name != new_version.name and version.state != secretmanager.SecretVersion.State.DESTROYED:
                try:
                    secret_client.destroy_secret_version(request={"name": version.name})
                except Exception as destroy_error:
                    print(f"[TIKTOK-SECRETS] Failed to destroy version {version.name}: {destroy_error}")

    except Exception as e:
        print(f"[TIKTOK-SECRETS] Error saving tokens to Secret Manager: {e}")


def refresh_tokens(brand: str, refresh_token: str):
    app_key, app_secret = get_app_credentials(brand)

    refresh_url = "https://auth.tiktok-shops.com/api/v2/token/refresh"
    params = {
        "app_key": app_key,
        "app_secret": app_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    }

    print(f"[TIKTOK-SECRETS] DEBUG url: {refresh_url} with params")

    try:
        response = requests.get(refresh_url, params=params)

        data = response.json().get("data", {})
        
        new_access_token = data.get("access_token")
        new_refresh_token = data.get("refresh_token")

        if new_access_token and new_refresh_token:
            save_tokens(brand, {
                "accessToken": new_access_token, 
                "refreshToken": new_refresh_token
            })
        else:
            print("[TIKTOK-SECRETS] New tokens dont exist")
    except Exception as e:
        print(f"[TIKTOK-SECRETS] Error refreshing tokens: {e}")


def get_shop_cipher(brand: str, access_token: str):
    try:
        app_key, app_secret = get_app_credentials(brand)
        
        timestamp = int(time.time())
        path = "/authorization/202309/shops"
        
        query_params = f"app_key{app_key}timestamp{timestamp}"
        result_string = f"{app_secret}{path}{query_params}{app_secret}"
        
        sign = hmac.new(
            app_secret.encode('utf-8'),
            result_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        base_url = f"https://open-api.tiktokglobalshop.com{path}"
        params = {
            "app_key": app_key,
            "sign": sign,
            "timestamp": timestamp
        }
        
        print(f"Hitting get shop cipher for brand: {brand}")
        
        headers = {
            "content-type": "application/json",
            "x-tts-access-token": access_token,
        }

        response = requests.get(base_url, params=params, headers=headers)
        
        response_data = response.json().get("data", {})
        authorized_shops = response_data.get("shops", [])
        
        shop_cipher = ""
        for shop in authorized_shops:
            shop_name = shop.get("name", "")
            print(f"Shop name: {shop_name}")
            if brand.lower() in shop_name.lower():
                shop_cipher = shop.get("cipher", "")

        return shop_cipher

    except Exception as e:
        print(f"Error get shop cipher on brand: {brand}")
        print(e)
        return None