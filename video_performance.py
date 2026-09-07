from auth import load_tokens, get_shop_cipher, get_app_credentials
import os, requests, hashlib, hmac, json, time, pandas as pd
from datetime import datetime, timedelta
from decimal import Decimal
from google.cloud import bigquery
from zoneinfo import ZoneInfo

SF = bigquery.SchemaField
_N, _S = "NUMERIC", "STRING"

STAGING_SCHEMA = [
    SF("brand", _S), SF("activity_date", "DATE"), SF("avg_customers", _N),
    SF("click_through_rate", _S), SF("duration", _N), SF("gmv", _N), SF("gpm", _N),
    SF("id", _S), SF("items_sold", _N),
    SF("products", "RECORD", mode="REPEATED", fields=[SF("id", _S), SF("name", _S)]),
    SF("sku_orders", _N), SF("title", _S), SF("username", _S), SF("video_post_time", _S),
    SF("views", _N), SF("hash_tags", _S, mode="REPEATED"),
    SF("creator_id", _S), SF("creator_username", _S), SF("creator_nickname", _S),
    SF("author_type", _S),
]
SCHEMA_COLS = [f.name for f in STAGING_SCHEMA]
NUMERIC_COLS = [f.name for f in STAGING_SCHEMA if f.field_type == _N]


def _struct_list(value, fields):
    # pyarrow needs every struct in the array to carry exactly the target's fields
    if not isinstance(value, list):
        return []
    return [{f: (None if v.get(f) is None else str(v.get(f))) for f in fields} for v in value]


def _string_list(value):
    if not isinstance(value, list):
        return []
    return [str(v) for v in value]


def to_bq_frame(df):
    """Coerce the cleaned frame to exactly the table's columns and types."""
    out = df.reindex(columns=SCHEMA_COLS).copy()
    out["products"] = out["products"].apply(lambda v: _struct_list(v, ("id", "name")))
    out["hash_tags"] = out["hash_tags"].apply(_string_list)
    for c in NUMERIC_COLS:
        # NUMERIC maps to arrow decimal128; float64 cannot convert, Decimal can
        out[c] = pd.to_numeric(out[c], errors="coerce").apply(
            lambda v: None if pd.isna(v) else Decimal(str(v))
        )
    return out

def generate_sign(app_secret, path, query_params, body=None):
    exclude_keys = {"access_token", "sign"}
    param_string = "".join(
        f"{key}{query_params[key]}"
        for key in sorted(query_params)
        if key not in exclude_keys
    )

    sign_string = f"{path}{param_string}"

    if body:
        sign_string += json.dumps(body, separators=(",", ":"))
    
    sign_string = f"{app_secret}{sign_string}{app_secret}"

    return hmac.new(
        app_secret.encode("utf-8"),
        sign_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

def fetch_video_performance(brand, start_date, end_date):
    tokens = load_tokens(brand)
    accessToken = tokens['accessToken']

    if(accessToken):
        shopCipher = get_shop_cipher(brand=brand, access_token=accessToken)
        creds = get_app_credentials(brand)
        
        if brand == "Mossèru": 
            brand = "Mosseru"
        if brand == "Cléviant":
            brand = "Cleviant"
        
        appKey = creds[0]
        appSecret = creds[1]

        url = 'https://open-api.tiktokglobalshop.com'
        path = '/analytics/202605/shop_videos/performance'
        uri = url + path

        startDate = datetime.strptime(start_date, "%Y-%m-%d").date()
        endDate = datetime.strptime(end_date, "%Y-%m-%d").date()
        one_day = timedelta(days=1)
        
        container = []
        while(startDate < endDate):

            day_ge = startDate.isoformat()
            day_lt = (startDate + one_day).isoformat()

            print("Start date: ", day_ge)
            print("End date: ", day_lt)
            
            hasNextPage = True
            pageToken = None
            while(hasNextPage):
                # retry transient API failures; the signature is timestamped so
                # every attempt has to be rebuilt and re-signed
                for attempt in range(5):
                    timestamp = int(time.time())
                    signParams = {
                        'app_key': appKey,
                        'timestamp': timestamp,
                        'shop_cipher': shopCipher,
                        'start_date_ge': day_ge,
                        'end_date_lt': day_lt,
                        'page_size': 100
                    }
                    if pageToken:
                        signParams['page_token'] = pageToken
                    sign = generate_sign(appSecret, path, signParams)

                    payload = {
                        'app_key': appKey,
                        'sign': sign,
                        'timestamp': timestamp,
                        'start_date_ge': day_ge,
                        'end_date_lt': day_lt,
                        'shop_cipher': shopCipher,
                        'page_size': 100
                    }
                    if pageToken:
                        payload['page_token'] = pageToken

                    headers = {
                        'content-type': 'application/json',
                        'x-tts-access-token': accessToken
                    }

                    r = requests.get(uri, headers=headers, params=payload)
                    res = r.json()

                    if(res.get("code") == 0):
                        break
                    if(attempt == 4):
                        raise RuntimeError(res)
                    print(f"  retry {attempt + 1}/4 after code {res.get('code')}")
                    time.sleep(2 ** attempt)

                # print(json.dumps(res, indent=2)[:500])
                data = res.get("data") or {}
                container.extend({"brand": brand, "activity_date": day_ge, **v} for v in (data.get("videos") or []))

                nextPageToken = data.get("next_page_token")
                if(nextPageToken and len(nextPageToken) > 0):
                    pageToken = nextPageToken
                else:
                    hasNextPage = False 
                
                time.sleep(0.5)
            
            startDate += one_day

        return container
    print("No access token provided.")

def merge(df):
    if df.empty:
        print("nothing to merge")
        return
    client = bigquery.Client()
    project = client.project
    dataset = "tiktok_analytics"
    target = f"{project}.{dataset}.shop_video_performance"
    staging = f"{project}.{dataset}.shop_video_performance_staging"

    staged = to_bq_frame(df)
    client.load_table_from_dataframe(
        staged, staging,
        job_config=bigquery.LoadJobConfig(
            write_disposition="WRITE_TRUNCATE",
            schema=STAGING_SCHEMA,
        ),
    ).result()

    keys = ["brand", "activity_date", "id"]
    cols = SCHEMA_COLS
    on_clause = " AND ".join(f"T.{k} = S.{k}" for k in keys)
    set_clause = ", ".join(f"T.{c} = S.{c}" for c in cols if c not in keys)
    insert_cols = ", ".join(cols)
    insert_vals = ", ".join(f"S.{c}" for c in cols)
    dates = sorted({d.isoformat() for d in staged['activity_date'] if pd.notna(d)})
    if not dates:
        print("no activity_date values to merge")
        return
    date_list = ", ".join(f"DATE '{d}'" for d in dates)

    client.query(f"""
        MERGE `{target}` T
        USING (
            SELECT * EXCEPT(_rn) FROM (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY brand, activity_date, id ORDER BY gmv DESC
                ) AS _rn
                FROM `{staging}`
            ) WHERE _rn = 1
        ) S
        ON {on_clause}
           AND T.activity_date IN ({date_list})
        WHEN MATCHED THEN UPDATE SET {set_clause}
        WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})
    """).result()
    
def video_performance(brand):
    today = datetime.now(ZoneInfo("Asia/Jakarta")).date()
    startDate = (today - timedelta(days=7)).isoformat()
    endDate = today.isoformat() 
    
    dataAug = fetch_video_performance(brand, startDate, endDate)

    if not dataAug:
        return

    df_aug = pd.DataFrame(dataAug) 
    df_aug['activity_date'] = pd.to_datetime(df_aug['activity_date']).dt.date
    df_aug['gmv'] = pd.to_numeric(df_aug['gmv'].str['amount'])
    df_aug['gpm'] = pd.to_numeric(df_aug['gpm'].str['amount'])
    df_aug['creator_id'] = df_aug['creator'].str['open_id'].astype(str)
    df_aug['creator_username'] = df_aug['creator'].str['user_name'].astype(str)
    df_aug['creator_nickname'] = df_aug['creator'].str['nick_name'].astype(str)
    df_aug['author_type'] = df_aug['creator'].str['author_type'].astype(str)
    
    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=30)
    vpt = pd.to_datetime(df_aug['video_post_time'])
    posted_by_then = vpt.dt.date <= df_aug['activity_date']
    df_aug_cleaned = df_aug[posted_by_then & ((df_aug['gmv'] > 0) | (vpt >= cutoff))]
    df_aug_cleaned = df_aug_cleaned.drop(columns='creator')

    merge(df_aug_cleaned)