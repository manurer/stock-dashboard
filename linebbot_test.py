import requests
import json

# 設定您的金鑰
CHANNEL_ACCESS_TOKEN = '89Ukm1gl1/hN9ukMh/ln5DSxkVqZRdrGhqcU3Y/VS/pqiu9FThnaeD+am/xjC1an6/QeUPTB1RAsol1BBvwOnQUvI8kEWJ5aI/uXArxm3UcWI47bgsXEt2uqTakdku+yFBx7fQ37Y3j6SrbJARz/fAdB04t89/1O/w1cDnyilFU='
USER_ID = 'Uae527ac05a0024c822f743e22f92473d'  # 必須是 U 開頭的那串

def send_line_message(msg):
    url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {CHANNEL_ACCESS_TOKEN}'
    }
    
    # 訊息格式 (可以傳送文字、貼圖、圖片)
    payload = {
        'to': USER_ID,
        'messages': [
            {
                'type': 'text',
                'text': msg
            }
        ]
    }

    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        # 檢查回應
        if response.status_code == 200:
            print("發送成功！")
        else:
            print(f"發送失敗: {response.status_code}, {response.text}")
            
    except Exception as e:
        print(f"發生錯誤: {e}")

# 測試發送
if __name__ == "__main__":
    send_line_message("這是透過 LINE Messaging API 發送的測試訊息！")