import os
import json
import logging
import requests
import asyncio
import uuid
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, JobQueue

# --- НАСТРОЙКИ ---
TELEGRAM_BOT_TOKEN = "8472246861:AAF599zkV7yjRjeKhoiVzdlgW4e-DD1e2WI"
LOCALAI_URL = "http://localhost:8080/v1/chat/completions"  # или внешний IP с LocalAI
RAPIDAPI_KEY = "3f7101256f6adfdda2c7430cf15ac5d7"
CHAT_ID = "8437661219" # Ваш ID чата для уведомлений
VALUE_LOW = 0.8
VALUE_HIGH = 6.0

# --- ЛОГИРОВАНИЕ ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- ФУНКЦИИ ---
def get_matches():
    """Получение предстоящих матчей с fixture_id"""
    url = "https://api-football-v1.rapidapi.com/v3/fixtures"
    headers = {
        'X-RapidAPI-Key': RAPIDAPI_KEY,
        'X-RapidAPI-Host': 'api-football-v1.rapidapi.com'
    }
    params = {
        'league': '39',  # Английская Премьер‑лига
        'season': '2024',
        'next': '10'     # Следующие 10 матчей
    }
    try:
        response = requests.get(url, headers=headers, params=params)
        data = response.json()
        return data.get('response', [])
    except Exception as e:
        logger.error(f"Ошибка получения матчей: {e}")
        return []

def analyze_with_ai(match_data):
    """Анализ матча через LocalAI с использованием fixture_id"""
    fixture_id = match_data['fixture']['id']
    home_name = match_data['teams']['home']['name']
    away_name = match_data['teams']['away']['name']
    date_str = match_data['fixture']['date']

    prompt = f"""Проанализируй футбольный матч и дай рекомендации для ставок.
Команды: {home_name} vs {away_name}
Дата: {date_str}
ID матча: {fixture_id}
Статистика команд: {match_data.get('statistics', 'нет данных')}
Учитывай:
- текущую форму команд (последние 5 матчей);
- историю личных встреч;
- фактор домашнего поля;
- травмы ключевых игроков;
- мотивацию (борьба за титул, вылет и т. д.).

Дай прогноз в формате JSON:
{{
  "fixture_id": {fixture_id},
  "match": "{home_name} vs {away_name}",
  "date": "{date_str}",
  "markets": [
    {{
      "market_type": "over2_5",
      "prob": 0.62,
      "odd": 2.10,
      "value": 1.30,
      "odd_id": "abc1"
    }},
    {{
      "market_type": "under2_5",
      "prob": 0.38,
      "odd": 1.95,
      "value": 0.74,
      "odd_id": "abc2"
    }},
    ... (добавь форы, ОЗ)
  ],
  "analysis_id": "{str(uuid.uuid4())}",
  "reason": "краткое обоснование"
}}"""

    payload = {
        "model": "mistral",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 800
    }

    try:
        response = requests.post(LOCALAI_URL, json=payload)
        return response.json()['choices'][0]['message']['content']
    except Exception as e:
        logger.error(f"Ошибка анализа ИИ: {e}")
        return None

async def monitor_matches(context: ContextTypes.DEFAULT_TYPE):
    """Мониторинг матчей и отправка прогнозов с id и value-фильтром"""
    matches = get_matches()

    for match in matches:
        analysis_raw = analyze_with_ai(match)
        if not analysis_raw:
            continue

        try:
            analysis = json.loads(analysis_raw)
            fixture_id = analysis.get('fixture_id')
            if not fixture_id:
                continue

            # Фильтруем рынки по value
            tips = []
            for mkt in analysis.get('markets', []):
                value = mkt.get('value')
                if VALUE_LOW <= value <= VALUE_HIGH:
                    tips.append(mkt)

            if not tips:
                continue

            # Формируем сообщение
            lines = [
                f"⚽ **Прогноз на матч**",
                f"**{analysis['match']}**",
                f"📅 Дата: {analysis['date']}",
                f"🆔 ID матча: {fixture_id}",
                f"🔎 **Рекомендации (value {VALUE_LOW}–{VALUE_HIGH}):**"
            ]

            for tip in tips:
                lines.append(
                    f"- {tip['market_type'].upper()}: "
                    f"P={tip['prob']:.2f}, кэф={tip['odd']:.2f}, value={tip['value']:.2f}, "
                    f"ID рынка: {tip.get('odd_id', 'нет')}"
                )

            lines.append(f"📝 **Обоснование**: {analysis.get('reason', '')}")

            message = "\n".join(lines)
            await context.bot.send_message(chat_id=CHAT_ID, text=message)

        except json.JSONDecodeError:
            logger.error("Неверный формат ответа от ИИ")
        except Exception as e:
            logger.error(f"Ошибка при обработке анализа: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Бот запущен! Используйте /check для ручной проверки.")

async def manual_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await monitor_matches(context)
    await update.message.reply_text("Проверка матчей завершена!")

def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("check", manual_check))

    job_queue: JobQueue = application.job_queue
    job_queue.run_repeating(monitor_matches, interval=21600, first=10)  # каждые 6 часов

    application.run_polling()

if __name__ == '__main__':
    main()
