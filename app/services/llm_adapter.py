from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, AsyncGenerator
import asyncio
from app.core.config import settings


class LLMAdapter(ABC):
    """Базовый класс для LLM адаптеров"""
    
    @abstractmethod
    async def generate(self, prompt: str, language: str = "en") -> str:
        """Сгенерировать ответ на основе промпта"""
        pass
    
    @abstractmethod
    async def generate_with_messages(self, messages: List[Dict[str, str]], language: str = "en") -> str:
        """Сгенерировать ответ на основе сообщений (chat format)"""
        pass
    
    async def generate_stream(self, prompt: str, language: str = "en") -> AsyncGenerator[str, None]:
        """Стриминговый генератор (по умолчанию - обычный generate)"""
        yield await self.generate(prompt, language)


# class OpenAIAdapter(LLMAdapter):
    """Адаптер для OpenAI GPT"""
    
    def __init__(self):
        self.client = None
    
    def _get_client(self):
        if self.client is None:
            from openai import AsyncOpenAI
            self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        return self.client
    
    async def generate(self, prompt: str, language: str = "en") -> str:
        client = self._get_client()
        if not client:
            return "LLM not configured"
        
        try:
            response = await client.chat.completions.create(
                # model="gpt-5.5",
                model="gpt-4.1-nano",
                messages=[{"role": "user", "content": prompt}],
                    temperature=1,
                    # temperature=0.1,
                    max_tokens=32768,
                timeout=300,
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Error: {str(e)}"
    
    async def generate_with_messages(self, messages: List[Dict[str, str]], language: str = "en") -> str:
        client = self._get_client()
        if not client:
            return "LLM not configured"
        
        # Добавляем язык в последнее сообщение если не en
        if language and language != "en":
            messages = messages.copy()
            last_msg = messages[-1].copy()
            if language == "ru":
                last_msg["content"] = "ОТВЕТЬ НА РУССКОМ ЯЗЫКЕ.\n\n" + last_msg.get("content", "")
            else:
                last_msg["content"] = f"ОТВЕТЬ НА ЯЗЫКЕ: {language.upper()}.\n\n" + last_msg.get("content", "")
            messages[-1] = last_msg
        
        try:
            response = await client.chat.completions.create(
                model="gpt-4.1-nano",
                # model="gpt-5.5",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=32768,
                timeout=300,
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Error: {str(e)}"


class ClaudeAdapter(LLMAdapter):
    """Адаптер для Anthropic Claude"""
    
    def __init__(self):
        self.client = None
        self._anthropic = None
    
    def _get_anthropic(self):
        if self._anthropic is None:
            try:
                from anthropic import AsyncAnthropic
                self._anthropic = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
            except ImportError:
                pass
        return self._anthropic
    
    async def generate(self, prompt: str, language: str = "en") -> str:
        anthropic = self._get_anthropic()
        if not anthropic:
            # Fallback к DeepSeek если Claude недоступен
            try:
                return await DeepSeekAdapter().generate(prompt, language)
            except Exception as e:
                return f"Error: Claude fallback failed - {str(e)}"
        
        if language and language != "en":
            if language == "ru":
                prompt = "ОТВЕТЬ НА РУССКОМ ЯЗЫКЕ.\n\n" + prompt
            else:
                prompt = f"ОТВЕТЬ НА ЯЗЫКЕ: {language.upper()}.\n\n" + prompt
        
        try:
            response = await anthropic.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=33000,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text
        except Exception as e:
            return f"Error: {str(e)}"
    
    async def generate_with_messages(self, messages: List[Dict[str, str]], language: str = "en") -> str:
        anthropic = self._get_anthropic()
        if not anthropic:
            return "Claude not configured"
        
        try:
            response = await anthropic.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=2000,
                messages=messages
            )
            return response.content[0].text
        except Exception as e:
            return f"Error: {str(e)}"


class OllamaAdapter(LLMAdapter):
    """Адаптер для локального Ollama LLM"""
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url or settings.OLLAMA_BASE_URL
        self.client = None
    
    def _get_client(self):
        if self.client is None:
            try:
                import httpx
                self.client = httpx.AsyncClient(base_url=self.base_url, timeout=120.0)
            except ImportError:
                pass
        return self.client
    
    async def generate(self, prompt: str, language: str = "en") -> str:
        client = self._get_client()
        if not client:
            return "Ollama not configured"
        
        try:
            response = await client.post(
                "/api/generate",
                json={
                    "model": "llama3",
                    "prompt": prompt,
                    "stream": False,
                }
            )
            if response.status_code == 200:
                return response.json().get("response", "No response")
            return f"Error: {response.status_code}"
        except Exception as e:
            return f"Error: {str(e)}"
    
    async def generate_with_messages(self, messages: List[Dict[str, str]], language: str = "en") -> str:
        prompt = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
        return await self.generate(prompt, language)


class GeminiAdapter(LLMAdapter):
    """Адаптер для Google Gemini"""
    
    def __init__(self):
        self.client = None
    
    def _get_client(self):
        if self.client is None:
            try:
                import google.genai as genai
                genai.configure(api_key=settings.GEMINI_API_KEY)
                self.client = genai.GenerativeModel('gemini-1.5-flash')
            except ImportError:
                try:
                    import google.generativeai as genai
                    genai.configure(api_key=settings.GEMINI_API_KEY)
                    self.client = genai.GenerativeModel('gemini-1.5-flash')
                except:
                    pass
        return self.client
    
    async def generate(self, prompt: str, language: str = "en") -> str:
        client = self._get_client()
        if not client:
            return "Gemini not configured"
        
        try:
            response = await client.generate_content_async(prompt)
            return response.text
        except Exception as e:
            return f"Error: {str(e)}"
    
    async def generate_with_messages(self, messages: List[Dict[str, str]], language: str = "en") -> str:
        client = self._get_client()
        if not client:
            return "Gemini not configured"
        
        try:
            prompt = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
            response = await client.generate_content_async(prompt)
            return response.text
        except Exception as e:
            return f"Error: {str(e)}"


class FallbackAdapter(LLMAdapter):
    """Заглушка когда LLM не настроен"""
    
    async def generate(self, prompt: str, language: str = "en") -> str:
        return "LLM not configured. Please set LLM_PROVIDER in .env file."
    
    async def generate_with_messages(self, messages: List[Dict[str, str]], language: str = "en") -> str:
        return "LLM not configured. Please set LLM_PROVIDER in .env file."

class DeepSeekAdapter(LLMAdapter):
    """Адаптер для DeepSeek"""
    
    def __init__(self):
        self.client = None
    
    def _get_client(self):
        if self.client is None:
            from openai import AsyncOpenAI
            self.client = AsyncOpenAI(
                api_key=settings.DEEPSEEK_API_KEY,
                base_url="https://api.deepseek.com"
            )
        return self.client
    
    async def generate(self, prompt: str, language: str = "en") -> str:
        client = self._get_client()
        try:
            response = await client.chat.completions.create(
                # model="deepseek-chat",  # это DeepSeek V3
                model="deepseek-v4-flash",  # это DeepSeek V4 Flash
                # model="deepseek-v4-pro",  # эксперимент: plans/synastry-before-batching.md — временно вернули flash, чтобы отделить model-effect от volume-effect (plans/synastry-aspect-type-verification.md, "Открытые вопросы")
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                # max_tokens=8000,
                max_tokens=32768,
                timeout=500,
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Error: {str(e)}"

    async def generate_with_messages(self, messages, language: str = "en") -> str:
        client = self._get_client()
        try:
            response = await client.chat.completions.create(
                model="deepseek-v4-flash",  # это DeepSeek V4 Flash
                # model="deepseek-v4-pro",  # эксперимент: plans/synastry-before-batching.md
                messages=messages,
                temperature=0.3,
                # max_tokens=32768,
                timeout=500,
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Error: {str(e)}"

    async def generate_stream(self, prompt: str, language: str = "en") -> AsyncGenerator[str, None]:
        """Стриминговый генератор для DeepSeek"""
        client = self._get_client()
        try:
            stream = await client.chat.completions.create(
                model="deepseek-v4-flash",
                # model="deepseek-v4-pro",  # эксперимент: plans/synastry-before-batching.md
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=32768,
                timeout=500,
                stream=True,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            yield f"Error: {str(e)}"

class OpenRouterAdapter(LLMAdapter):
    """Адаптер OpenRouter: OpenAI-совместимый API, любая модель по слагу"""

    def __init__(self, model: Optional[str] = None):
        self.model = model or settings.OPENROUTER_MODEL
        self.client = None

    def _get_client(self):
        if self.client is None:
            from openai import AsyncOpenAI
            self.client = AsyncOpenAI(
                api_key=settings.OPENROUTER_API_KEY,
                base_url="https://openrouter.ai/api/v1",
            )
        return self.client

    def _with_language(self, text: str, language: str) -> str:
        if language and language != "en":
            if language == "ru":
                return "ОТВЕТЬ НА РУССКОМ ЯЗЫКЕ.\n\n" + text
            return f"ОТВЕТЬ НА ЯЗЫКЕ: {language.upper()}.\n\n" + text
        return text

    async def generate(self, prompt: str, language: str = "en") -> str:
        if not settings.OPENROUTER_API_KEY:
            return "Error: OPENROUTER_API_KEY not configured"
        try:
            response = await self._get_client().chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": self._with_language(prompt, language)}],
                temperature=0.3,
                max_tokens=4096,
                timeout=300,
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Error: {str(e)}"

    async def generate_with_messages(self, messages: List[Dict[str, str]], language: str = "en") -> str:
        if not settings.OPENROUTER_API_KEY:
            return "Error: OPENROUTER_API_KEY not configured"
        if language and language != "en" and messages:
            messages = messages.copy()
            last_msg = messages[-1].copy()
            last_msg["content"] = self._with_language(last_msg.get("content", ""), language)
            messages[-1] = last_msg
        try:
            response = await self._get_client().chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,
                max_tokens=4096,
                timeout=300,
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Error: {str(e)}"


_adapters = {
    'deepseek': DeepSeekAdapter,
    'claude': ClaudeAdapter,
    'ollama': OllamaAdapter,
    'gemini': GeminiAdapter,
}


def get_llm_adapter(provider: str = None, model: str = None) -> LLMAdapter:
    """Получить адаптер для указанного LLM провайдера.
    model используется только для openrouter (слаг модели)."""
    if provider is None:
        provider = settings.LLM_PROVIDER

    provider = provider.lower()

    if provider == 'openrouter':
        return OpenRouterAdapter(model)

    adapter_class = _adapters.get(provider, FallbackAdapter)
    return adapter_class()


async def generate_analysis(
    prompt: str,
    language: str = "en",
    provider: str = None
) -> str:
    """Удобная функция для генерации анализа"""
    adapter = get_llm_adapter(provider)
    return await adapter.generate(prompt, language)


async def generate_chat_analysis(
    messages: List[Dict[str, str]],
    language: str = "en",
    provider: str = None
) -> str:
    """Удобная функция для генерации анализа сchat format"""
    adapter = get_llm_adapter(provider)
    return await adapter.generate_with_messages(messages, language)