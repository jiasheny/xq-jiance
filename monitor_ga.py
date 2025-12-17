# monitor_ga.py (交易时间监测版 - 包含中文注释)

import warnings
warnings.filterwarnings(
    "ignore",
    message="pkg_resources is deprecated as an API.*",
    category=UserWarning
)

import pysnowball as ball
# 重新引入 dtime 用于时间判断
from datetime import datetime, timedelta, time as dtime, timezone 
import configparser
import requests
import json
import os
import pytz
import sys

# 解决 configparser 读取时对大小写的敏感问题
class CaseSensitiveConfigParser(configparser.ConfigParser):
    def optionxform(self, optionstr):
        return optionstr

config = CaseSensitiveConfigParser()
config.read("config.ini", encoding='utf-8')

# --- 1. 配置读取 ---
sct_send_key = config.get('default', 'sct_send_key', fallback='')
xq_a_token = config.get('default', 'xq_a_token', fallback='')
u = config.get('default', 'u', fallback='')
wecom_webhook = config.get('default', 'wecom_webhook', fallback='')
xq_id_token = config.get('default', 'xq_id_token', fallback='')
xq_r_token = config.get('default', 'xq_r_token', fallback='')

# 从 [notify_mapping] 部分获取所有需要监控的组合ID列表
notify_mapping = {}
if config.has_section('notify_mapping'):
    notify_mapping = dict(config.items('notify_mapping'))

cube_ids = list(notify_mapping.keys())
if not cube_ids:
    print("ERROR: No cube IDs configured.")
    sys.exit(1)

# 全局状态标志
cookie_expired_notified = False
processed_ids_file = "processed_ids.json"

# --- 2. 状态/数据加载 ---
def load_processed_ids():
    """加载已处理的调仓ID，防止重复推送"""
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

# 设置 pysnowball 库的 Cookie 认证信息
if xq_a_token: ball.set_token(";".join([f"xq_a_token={xq_a_token}", f"u={u}", f"xq_id_token={xq_id_token}", f"xq_r_token={xq_r_token}"]))
print("Cookie \u5df2\u8bbe\u7f6e") # Cookie 已设置

UTC = timezone.utc
SHANGHAI_TZ = pytz.timezone('Asia/Shanghai')

# --- 3. 交易时间判断逻辑 (新增) ---
def is_trading_time(now):
    """判断当前时间是否在 A 股交易时间 (9:30-11:30, 13:00-15:00)"""
    if now.weekday() >= 5: return False # 0-4 是周一到周五
    current_time = now.time()
    # 上午交易时间
    if dtime(9, 30) <= current_time <= dtime(11, 30): return True
    # 下午交易时间
    if dtime(13, 0) <= current_time <= dtime(15, 0): return True
    return False

# --- 4. 辅助函数 ---
def format_timestamp_with_timezone_adjustment(timestamp, hours=0):
    """将时间戳转换为上海时区的可读格式"""
    dt_obj = datetime.fromtimestamp(timestamp / 1000, tz=UTC)
    dt_obj = dt_obj + timedelta(hours=hours)
    return dt_obj.astimezone(SHANGHAI_TZ).strftime('%Y.%m.%d %H:%M:%S')

def send_wecom_message(title, content):
    """发送企业微信群机器人 Text 消息"""
    if not wecom_webhook: return
    
    # 将标题和内容合并，适合 Text 格式
    text_content = f"{title}\n\n{content}"
    
    # 更改 msgtype 为 text，并使用 text 字段
    data = { "msgtype": "text", "text": { "content": text_content } }
    
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
    """发送 Server酱 (FTQQ) 消息 (可选)"""
    if not sct_send_key: return
    url = f"https://sctapi.ftqq.com/{sct_send_key}.send"
    data = { "title": "\u96ea\u7403\u7ec4\u5408\u65b0\u8c03\u4ed3\u901a\u77e5", "desp": content }
    try:
        requests.post(url, data=data, timeout=10)
    except Exception:
        pass

def save_processed_ids():
    """保存已处理的调仓ID到文件"""
    try:
        with open(processed_ids_file, 'w', encoding='utf-8') as f:
            json.dump(list(processed_ids), f)
    except Exception:
        pass

# --- 5. 核心监控逻辑 ---
def monitor_rebalancing_operations():
    """遍历所有组合ID，检查是否有新的调仓操作"""
    global cookie_expired_notified
    
    for cube_id in cube_ids:
        try:
            # 1. 获取组合基本信息
            quote_response = ball.quote_current(cube_id)
            if not quote_response: continue
            
            # 成功访问API，如果之前发过Cookie过期提醒，则重置状态
            if cookie_expired_notified:
                print("\u68c0\u6d4b\u5230API\u8c03\u7528\u6210\u529f\uff0c\u91cd\u7f6e\u72b6\u6001") 
                cookie_expired_notified = False

            quote_info = quote_response.get(cube_id, {})
            name = quote_info.get("name", "Unknown")
            
            # 2. 获取最新调仓记录
            rebalancing_response = ball.rebalancing_current(cube_id)
            if not rebalancing_response: continue
            last_rb = rebalancing_response.get('last_rb')

            # 3. 检查是否为新调仓
            if last_rb and last_rb.get('id') not in processed_ids:
                
                # 构建通知内容
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

                # 4. 获取调仓详情
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
                
                # 5. 发送通知
                if sct_send_key:
                    send_serverchan_message(content)
                
                if wecom_webhook:
                    wecom_title = f"\u96ea\u7403\u7ec4\u5408\u65b0\u8c03\u4ed3\uff1a{name}"
                    send_wecom_message(wecom_title, content) # 使用新的 Text 格式函数

                # 6. 保存状态
                save_processed_ids()
        
        # 7. 异常处理 (Cookie 失效)
        except Exception as e:
            error_str = str(e)
            print(f"Error {cube_id}: {error_str}")
            
            if "400016" in error_str:
                if not cookie_expired_notified:
                    print("\u91cd\u8981\uff1aCookie \u5df2\u8fc7\u671f\uff01\u6b63\u5728\u53d1\u9001\u4f01\u4e1a\u5fae\u4fe1\u63d0\u9192...")
                    
                    wecom_title = "\u3010\u96ea\u7403\u76d1\u63a7\u3011Cookie\u5df2\u8fc7\u671f\uff01"
                    wecom_content = f"**\u9519\u8bef\u4ee3\u7801:** 400016\n**\u8bf7\u6c42\u7ec4\u5408:** {cube_id}\n**\u63d0\u793a:** \u8bf7\u7acb\u5373\u66f4\u65b0 GitHub Secrets \u4e2d\u7684 `XQ_A_TOKEN` \u548c `U_COOKIE`\u3002"
                    
                    if wecom_webhook:
                        send_wecom_message(wecom_title, wecom_content) # 使用新的 Text 格式函数
                        cookie_expired_notified = True 

# --- 6. 主程序入口 ---
if __name__ == '__main__':
    now_shanghai = datetime.now(SHANGHAI_TZ)
    print(f"\u5f53\u524d\u65f6\u95f4 {now_shanghai.strftime('%Y.%m.%d %H:%M:%S')}") # 当前时间

    # ***** 关键修正：检查是否在交易时间 (非交易时间测试时请注释掉以下三行) *****
    #if not is_trading_time(now_shanghai):
         #print("\u8df3\u8fc7\u76d1\u6d4b\uff1a\u975e\u4ea4\u6613\u65f6\u95f4") # 跳过监测：非交易时间
         #sys.exit(0)

    try:
        print(">>> \u5f00\u59cb\u67e5\u8be2\u7ec4\u5408\u8c03\u4ed3...") # 正在查询
        monitor_rebalancing_operations()
    except Exception as e:
        print(f"Job Error: {e}")
    finally:
        sys.exit(0) # 退出，等待 GitHub Actions 再次调度
