# -*- coding: utf-8 -*-
import os
import easyocr
import aiohttp
import json
import yaml
import ssl
from dotenv import load_dotenv
from PIL import Image
from aiogram import Bot, Dispatcher, types
from aiogram.dispatcher import FSMContext
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram import exceptions
import datetime
import asyncio
import re

print("aiogram version:", __import__('aiogram').__version__)

def load_config():
    with open("config.yaml", "r", encoding="utf-8") as file:
        return yaml.safe_load(file)

def increase_image_resolution(image_path, scale_factor=2):
    image = Image.open(image_path)
    new_size = (int(image.width * scale_factor), int(image.height * scale_factor))
    resized_image = image.resize(new_size, Image.ANTIALIAS)
    resized_image_path = image_path.replace(".jpg", "_resized.jpg")
    resized_image.save(resized_image_path)
    return resized_image_path

load_dotenv()
ssl._create_default_https_context = ssl._create_unverified_context

API_KEY = os.getenv("API_KEY")
TOKEN = os.getenv("TOKEN")

print("API_KEY =", API_KEY)
print("TOKEN =", TOKEN)


reader = easyocr.Reader(["ru", "en"], gpu=False)
storage = MemoryStorage()
bot = Bot(token=TOKEN)
dp = Dispatcher(bot, storage=storage)
result_storage_path = "temp"
print("Готов к работе")

config = load_config()
system_prompt = config["system_prompt"]

def split_message(message, max_length=4096):
    parts = []
    while len(message) > max_length:
        part = message[:max_length]
        last_newline = part.rfind("\n")
        if last_newline != -1:
            parts.append(part[:last_newline])
            message = message[last_newline + 1:]
        else:
            parts.append(part)
            message = message[max_length:]
    parts.append(message)
    return parts


async def save_images_from_message(photos_data):
    date = f"{datetime.date.today()}"
    images_path = []
    for photo in photos_data:
        path = os.path.join("temp", date)
        os.makedirs(path, exist_ok=True)
        file_path = os.path.join(path, photo.file_id + ".jpg")
        await photo.download(destination_file=file_path)
        images_path.append(file_path)
    return images_path


async def request_to_groq_for_test(photos_data, system_prompt, message):
    images = await save_images_from_message(photos_data)
    all_text = []


    for image_name in images:
        result = reader.readtext(image_name, detail=0)
        all_text.extend(result)


    all_text_str = "\n".join(all_text)


    lines = all_text_str.split("\n")
    question_lines = []
    options_lines = []

    for line in lines:
        line_clean = line.replace("□", "").strip()
        if re.match(r"^[0-9]+[\).\s]|^[A-Da-d][\).\s]|^□", line_clean):
            options_lines.append(line_clean)
        else:
            question_lines.append(line_clean)

    question_text = " ".join(question_lines)
    options_text = ", ".join([re.sub(r"^[0-9A-Da-d][\).\s]*", "", opt) for opt in options_lines])


    question_with_options = f"{question_text}\nВарианты: {options_text}" if options_text else question_text

    prompt = f"""
Вопрос: {question_with_options}

Выбери правильный ответ и напиши строго текст ответа (без букв), в формате JSON:
{{
  "right_answer": "<текст правильного ответа>"
}}
"""


    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=data, headers=headers) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    print("Ошибка Groq:", resp.status, text)
                    response_content = {"right_answer": "Ошибка при запросе"}
                else:
                    response_json = await resp.json()
                    generated_text = response_json["choices"][0]["message"]["content"]
                    response_content = json.loads(generated_text)
    except Exception as e:
        print("Ошибка при запросе Groq:", e)
        response_content = {"right_answer": "Ошибка при генерации"}


    answer_text = response_content.get("right_answer", "Нет ответа")

    reply_message = (
        f"ВОПРОС:\n{question_with_options}\n\n"
        f"ОТВЕТ:\n{answer_text}"
    )


    parts = split_message(reply_message)
    for part in parts:
        try:
            await message.reply(part)
        except exceptions.TelegramAPIError as e:
            print("Ошибка отправки сообщения:", e)



@dp.message_handler(content_types=["photo"])
async def photo_handler(message: types.Message):
    photos_list = [message.photo[-1]]
    await request_to_groq_for_test(photos_list, system_prompt, message)


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    print("Бот запущен")
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True)
