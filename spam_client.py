from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.functions.channels import LeaveChannelRequest
import logging

class SpamClient:
    def __init__(self, session_name, api_id, api_hash):
        self.client = TelegramClient(
            session_name,
            api_id,
            api_hash,
            system_version='4.16.30-vxCUSTOM',
            connection_retries=10,
            retry_delay=5
        )
        logging.basicConfig(level=logging.INFO)

    async def __aenter__(self):
        try:
            await self.client.start()
            return self
        except FloodWaitError as e:
            logging.error(f"Flood wait: {e.seconds} seconds")
            raise

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.disconnect()

    async def leave_chat(self, chat_id):
        try:
            await self.client(LeaveChannelRequest(chat_id))
            logging.info(f"Аккаунт вышел из чата {chat_id}")
        except Exception as e:
            logging.error(f"Ошибка при выходе из чата {chat_id}: {str(e)}")
            raise

    def __getattr__(self, name):
        return getattr(self.client, name)

