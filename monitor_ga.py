# monitor_ga.py (GitHub Actions Final Version - Clean & WeCom Only)

import warnings
warnings.filterwarnings(
    "ignore",
    message="pkg_resources is deprecated as an API.*",
    category=UserWarning
)

import pysnowball as ball
from datetime import datetime, timedelta, time as dtime, timezone
import configparser
import requests
import json
import os
import pytz
import sys

class CaseSensitiveConfigParser(configparser.ConfigParser):
    def optionxform(self, optionstr):
        return optionstr

config = CaseSensitiveConfigParser()
config.read("config.ini", encoding='utf-8')

# Configuration
sct_send_key = config.get('default', 'sct_send_key', fallback='')
xq_a_token = config.get('default', 'xq_a_token', fallback='')
u = config.get('default', 'u', fallback='')
wecom_webhook = config.get('default', 'wecom_webhook', fallback='')
xq_id_token = config.get('default', 'xq_id_token', fallback='')
xq_r_token = config.get('default', 'xq_r_token', fallback='')

notify_mapping = {}
if config.has_section('notify_mapping'):
    notify_mapping = dict(config.items('notify_mapping'))

cube_ids = list(notify_mapping.keys())
if not cube_ids:
    print("ERROR: No cube IDs configured.")
    sys.exit(1)

# Global status
cookie_expired_notified = False
processed_ids_file = "processed_ids.json"

def load_processed_ids():
    if os.path.exists(processed_ids_file):
        try:
            with open(processed_ids_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, list):
                return set(data)
            with open(processed_ids_file, 'w', encoding='utf-8') as f:
                json.dump([], f)
            return set()
        except Exception:
            with open(processed_ids_file, 'w', encoding='utf-8') as f:
                json.dump([], f)
            return set()
    else:
        with open(processed_ids_file, 'w', encoding='utf-8') as f:
            json.dump([], f)
        return set()

processed_ids = load_processed_ids()

if xq_a_token: ball.set_token(";".join([f"xq_a_token={xq_a_token}", f"u={u}", f"xq_id_token={xq_id_token}", f"xq_r_token={xq_r_token}"]))
print("Cookie \u5df2\u8bbe\u7f6e") # Cookie 已设置

UTC = timezone.utc
SHANGHAI_TZ = pytz.timezone('Asia/Shanghai')

def is_trading_time(now):
    if now.weekday() >= 5: return False
    current_time = now.time()
    if dtime(9, 30) <= current_time <= dtime(11, 30): return True
    if dtime(13, 0) <= current_time <= dtime(15, 0): return True
    return False

def format_timestamp_with_timezone_adjustment(timestamp, hours=0):
    dt_obj = datetime.fromtimestamp(timestamp / 1000, tz=UTC)
    dt_obj = dt_obj + timedelta(hours=hours)
    return dt_obj.astimezone(SHANGHAI_TZ).strftime('%Y.%m.%d %H:%M:%S')

def send_wecom_message(title, content):
    if not wecom_webhook: return
    
    markdown_content = f"## \u96ea\u7403\u7ec4\u5408\u65b0\u8c03\u4ed3\n" 
    markdown_content += content.replace('\n', '\n>') 
    
    data = { "msgtype": "markdown", "markdown": { "content": markdown_content } }
    
    try:
        response = requests.post(wecom_webhook, headers={'Content-Type': 'application/json'}, json=data, timeout=10)
        result = response.json()
        if result.get("errcode") == 0:
            print("✅ \u4f01\u4e1a\u5fae\u4fe1\u6d88\u606f\u53d1\u9001\u6210\u529f")
        else:
            print(f"❌ \u4f01\u4e1a\u5fae\u4fe1\u6d88\u606f\u53d1\u9001\u5931\u8d25\uff1a{result.get('errmsg', 'Unknown error')}")
    except Exception as e:
        print(f"❌ \u53d1\u9001\u4f01\u4e1a\u5fae\u4fe1\u6d88\u606f\u65f6\u51fa\u9519\uff1a{e}")

def send_serverchan_message(content):
    if not sct_send_key: return
    url = f"https://sctapi.ftqq.com/{sct_send_key}.send"
    data = { "title": "\u96ea\u7403\u7ec4\u5408\u65b0\u8c03\u4ed3\u901a\u77e5", "desp": content }
    try:
        requests.post(url, data=data, timeout=10)
    except Exception:
        pass

def save_processed_ids():
    try:
        with open(processed_ids_file, 'w', encoding='utf-8') as f:
            json.dump(list(processed_ids), f)
    except Exception:
        pass

def monitor_rebalancing_operations():
    global cookie_expired_notified
    
    for cube_id in cube_ids:
        try:
            quote_response = ball.quote_current(cube_id)
            if not quote_response: continue
            
            if cookie_expired_notified:
                print("\u68c0\u6d4b\u5230API\u8c03\u7528\u6210\u529f\uff0c\u91cd\u7f6e\u72b6\u6001")
                cookie_expired_notified = False

            quote_info = quote_response.get(cube_id, {})
            name = quote_info.get("name", "Unknown")
            
            rebalancing_response = ball.rebalancing_current(cube_id)
            if not rebalancing_response: continue
            last_rb = rebalancing_response.get('last_rb')

            if last_rb and last_rb.get('id') not in processed_ids:
                content = f"\u68c0\u6d4b\u5230\u65b0\u8c03\u4ed3\u64cd\u4f5c\uff0c\u7ec4\u5408ID: {cube_id}\n"
                content += f"\u7ec4\u5408\u540d\u79f0: {name}\n"
                content += f"  \u6700\u65b0\u7684\u4e00\u6b21\u8c03\u4ed3:\n"
                content += f"    ID: {last_rb.get('id')}\n"
                content += f"    \u72b6\u6001: {last_rb.get('status')}\n"
                
                created_at_val = last_rb.get('created_at')
                if created_at_val:
                    created_at = format_timestamp_with_timezone_adjustment(created_at_val)
                    content += f"    \u65f6\u95f4: {created_at}\n"
                
                rebalancing_id = last_rb.get('id')
                processed_ids.add(rebalancing_id)

                history_response = ball.rebalancing_history(cube_id, 5, 1)
                found_history = False
                if history_response:
                    history_list = history_response.get('list', [])
                    for history_item in history_list:
                        if history_item.get('id') == rebalancing_id:
                            found_history = True
                            rebalancing_items = history_item.get('rebalancing_items', [])
                            if not rebalancing_items:
                                rebalancing_items = history_item.get('rebalancing_histories', [])
                            
                            for item in rebalancing_items:
                                stock_name = item.get('stock_name', 'Unknown')
                                stock_symbol = item.get('stock_symbol', item.get('stock_code', 'N/A'))
                                prev_weight = item.get('prev_weight') or 0
                                target_weight = item.get('target_weight', item.get('weight')) or 0
                                price = item.get('price', 'N/A')
                                
                                content += f"    \u80a1\u7968: {stock_name} ({stock_symbol})\n"
                                content += f"    \u4ef7\u683c: {price}\n"
                                content += f"    \u6743\u91cd: {prev_weight}% -> {target_weight}%\n"
                
                if not found_history:
                    content += "    (\u672a\u83b7\u53d6\u5230\u8be6\u7ec6\u5217\u8868)\n"

                print(content)
                
                if sct_send_key:
                    send_serverchan_message(content)
                
                if wecom_webhook:
                    wecom_title = f"\u96ea\u7403\u7ec4\u5408\u65b0\u8c03\u4ed3\uff1a{name}"
                    send_wecom_message(wecom_title, content)

                save_processed_ids()
        
        except Exception as e:
            error_str = str(e)
            print(f"Error {cube_id}: {error_str}")
            
            if "400016" in error_str:
                if not cookie_expired_notified:
                    print("\u91cd\u8981\uff1aCookie \u5df2\u8fc7\u671f\uff01\u6b63\u5728\u53d1\u9001\u4f01\u4e1a\u5fae\u4fe1\u63d0\u9192...")
                    
                    wecom_title = "\u3010\u96ea\u7403\u76d1\u63a7\u3011Cookie\u5df2\u8fc7\u671f\uff01"
                    wecom_content = f"**\u9519\u8bef\u4ee3\u7801:** 400016\n**\u8bf7\u6c42\u7ec4\u5408:** {cube_id}\n**\u63d0\u793a:** \u8bf7\u7acb\u5373\u66f4\u65b0 GitHub Secrets \u4e2d\u7684 `XQ_A_TOKEN` \u548c `U_COOKIE`\u3002"
                    
                    if wecom_webhook:
                        send_wecom_message(wecom_title, wecom_content)
                        cookie_expired_notified = True 

# --- Main Execution Block ---
if __name__ == '__main__':
    now_shanghai = datetime.now(SHANGHAI_TZ)
    print(f"\u5f53\u524d\u65f6\u95f4 {now_shanghai.strftime('%Y.%m.%d %H:%M:%S')}")

    if not is_trading_time(now_shanghai):
        print("\u8df3\u8fc7\u76d1\u6d4b\uff1a\u975e\u4ea4\u6613\u65f6\u95f4")
        sys.exit(0)

    try:
        print(">>> \u6b63\u5728\u4ea4\u6613\u65f6\u95f4\uff0c\u5f00\u59cb\u67e5\u8be2...")
        monitor_rebalancing_operations()
    except Exception as e:
        print(f"Job Error: {e}")
    finally:
        sys.exit(0)
