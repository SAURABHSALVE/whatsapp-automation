import os
import logging
from datetime import datetime

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from openai import OpenAI

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    DateTime
)

from sqlalchemy.orm import declarative_base, sessionmaker


# =========================================================
# LOAD ENV VARIABLES
# =========================================================

load_dotenv()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")


# =========================================================
# LOGGING CONFIG
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


# =========================================================
# FASTAPI APP
# =========================================================

app = FastAPI()


# =========================================================
# OPENAI CLIENT
# =========================================================

client = OpenAI(api_key=OPENAI_API_KEY)


# =========================================================
# DATABASE SETUP
# =========================================================

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


# =========================================================
# DATABASE MODEL
# =========================================================

class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)

    sender = Column(String, index=True)

    role = Column(String)

    content = Column(Text)

    timestamp = Column(DateTime, default=datetime.utcnow)


# Create tables automatically
Base.metadata.create_all(bind=engine)


# =========================================================
# SAVE MESSAGE TO DATABASE
# =========================================================

def save_message(sender, role, content):

    db = SessionLocal()

    try:
        message = Message(
            sender=sender,
            role=role,
            content=content
        )

        db.add(message)

        db.commit()

    except Exception as e:
        logger.error("DATABASE SAVE ERROR: %s", str(e))

    finally:
        db.close()


# =========================================================
# GET CHAT HISTORY
# =========================================================

def get_chat_history(sender, limit=10):

    db = SessionLocal()

    try:
        messages = (
            db.query(Message)
            .filter(Message.sender == sender)
            .order_by(Message.timestamp.desc())
            .limit(limit)
            .all()
        )

        history = []

        for msg in reversed(messages):

            history.append({
                "role": msg.role,
                "content": msg.content
            })

        return history

    except Exception as e:
        logger.error("DATABASE FETCH ERROR: %s", str(e))
        return []

    finally:
        db.close()


# =========================================================
# ASK OPENAI
# =========================================================

def ask_ai(sender, user_message):

    history = get_chat_history(sender)

    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful WhatsApp AI assistant. "
                "Reply politely and clearly."
            )
        }
    ]

    messages.extend(history)

    messages.append({
        "role": "user",
        "content": user_message
    })

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.7
    )

    ai_reply = response.choices[0].message.content

    return ai_reply


# =========================================================
# SEND WHATSAPP MESSAGE
# =========================================================

def send_message(to, message_text):

    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"

    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {
            "body": message_text[:4000]
        }
    }

    try:

        response = requests.post(
            url,
            headers=headers,
            json=payload
        )

        logger.info("META RESPONSE STATUS: %s", response.status_code)

        logger.info("META RESPONSE JSON: %s", response.json())

    except Exception as e:
        logger.error("WHATSAPP SEND ERROR: %s", str(e))


# =========================================================
# WEBHOOK VERIFICATION
# =========================================================

@app.get("/webhook")
async def verify_webhook(request: Request):

    mode = request.query_params.get("hub.mode")

    token = request.query_params.get("hub.verify_token")

    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:

        return PlainTextResponse(challenge)

    return PlainTextResponse(
        "Verification failed",
        status_code=403
    )


# =========================================================
# MAIN WEBHOOK
# =========================================================

@app.post("/webhook")
async def webhook(request: Request):

    data = await request.json()

    logger.info("FULL PAYLOAD: %s", data)

    try:

        value = data["entry"][0]["changes"][0]["value"]

        # Ignore status updates
        if "messages" not in value:

            logger.info("STATUS EVENT RECEIVED")

            return {"status": "ignored"}

        incoming_message = value["messages"][0]

        sender = incoming_message["from"]

        message_type = incoming_message.get("type")

        if message_type != "text":

            send_message(
                sender,
                "Currently I support text messages only."
            )

            return {"status": "unsupported_message_type"}

        user_text = incoming_message["text"]["body"]

        logger.info("USER MESSAGE: %s", user_text)

        # Save user message
        save_message(
            sender=sender,
            role="user",
            content=user_text
        )

        # Get AI response
        ai_reply = ask_ai(sender, user_text)

        logger.info("AI REPLY: %s", ai_reply)

        # Save AI response
        save_message(
            sender=sender,
            role="assistant",
            content=ai_reply
        )

        # Send WhatsApp reply
        send_message(sender, ai_reply)

    except Exception as e:

        logger.error("WEBHOOK ERROR: %s", str(e))

    return {"status": "ok"}
