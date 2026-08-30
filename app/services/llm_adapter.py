from abc import ABC, abstractmethod
from typing import Optional, List, Dict, AsyncGenerator
from app.core.config import settings


class LLMAdapter(ABC):
    """Base class for LLM adapters"""

    @abstractmethod
    async def generate(self, prompt: str, language: str = "en") -> str:
        """Generate a response from a prompt"""
        pass

    @abstractmethod
    async def generate_with_messages(self, messages: List[Dict[str, str]], language: str = "en") -> str:
        """Generate a response from messages (chat format)"""
        pass

    async def generate_stream(self, prompt: str, language: str = "en") -> AsyncGenerator[str, None]:
        """Streaming generator (default: falls back to plain generate)"""
        yield await self.generate(prompt, language)

    async def generate_stream_with_messages(self, messages: List[Dict[str, str]], language: str = "en") -> AsyncGenerator[str, None]:
        """Streaming generator for chat-format messages (default: falls back to plain generate_with_messages)"""
        yield await self.generate_with_messages(messages, language)


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
        
        # Add the language to the last message if not en
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
    """Adapter for Anthropic Claude"""
    
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
            # Fallback to DeepSeek if Claude is unavailable
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
    """Adapter for local Ollama LLM"""
    
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
    """Adapter for Google Gemini"""
    
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
    """Stub for when no LLM is configured"""
    
    async def generate(self, prompt: str, language: str = "en") -> str:
        return "LLM not configured. Please set LLM_PROVIDER in .env file."
    
    async def generate_with_messages(self, messages: List[Dict[str, str]], language: str = "en") -> str:
        return "LLM not configured. Please set LLM_PROVIDER in .env file."

class DeepSeekAdapter(LLMAdapter):
    """Adapter for DeepSeek"""

    # deepseek-v4-flash's real output ceiling is 384000 tokens (1,048,576 total
    # context, shared with the prompt) — 32768 was an arbitrary, much lower
    # number that silently truncated large analyses (full synastry prompts can
    # run ~250K tokens on their own). Set to 45000 (user's choice) — well
    # under the model's ceiling, still ~1.4x the old 32768.
    MAX_TOKENS = 45000

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
                # model="deepseek-chat",  # this is DeepSeek V3
                model="deepseek-v4-flash",  # this is DeepSeek V4 Flash
                # model="deepseek-v4-pro",  # experiment: plans/synastry-before-batching.md — temporarily reverted to flash to separate the model-effect from the volume-effect (plans/synastry-aspect-type-verification.md, "Open questions")
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                # max_tokens=8000,
                max_tokens=self.MAX_TOKENS,
                timeout=500,
            )
            # finish_reason tells a complete answer from a silently truncated one:
            # 'stop' — the model finished on its own; 'length' — it hit max_tokens
            # above and the text is cut off mid-sentence. Without this the caller
            # gets a truncated analysis and returns 200 OK with nothing in the log.
            choice = response.choices[0]
            usage = getattr(response, "usage", None)
            print(
                f"[DeepSeekAdapter] finish_reason={choice.finish_reason}"
                f" completion_tokens={getattr(usage, 'completion_tokens', '?')}"
                f" max_tokens={self.MAX_TOKENS}"
            )
            return choice.message.content
        except Exception as e:
            return f"Error: {str(e)}"

    async def generate_with_messages(self, messages, language: str = "en") -> str:
        client = self._get_client()
        try:
            response = await client.chat.completions.create(
                model="deepseek-v4-flash",  # this is DeepSeek V4 Flash
                # model="deepseek-v4-pro",  # experiment: plans/synastry-before-batching.md
                messages=messages,
                temperature=0.3,
                # max_tokens=32768,
                timeout=500,
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Error: {str(e)}"

    async def generate_stream(self, prompt: str, language: str = "en") -> AsyncGenerator[str, None]:
        """Streaming generator for DeepSeek"""
        async for chunk in self._stream_completion([{"role": "user", "content": prompt}]):
            yield chunk

    async def generate_stream_with_messages(self, messages: List[Dict[str, str]], language: str = "en") -> AsyncGenerator[str, None]:
        """Streaming generator for DeepSeek, chat-format messages (used by chat streaming) —
        same underlying call as generate_stream, just messages passed straight through
        instead of wrapped as a single user prompt."""
        async for chunk in self._stream_completion(messages):
            yield chunk

    async def _stream_completion(self, messages: List[Dict[str, str]]) -> AsyncGenerator[str, None]:
        """Shared streaming call behind generate_stream/generate_stream_with_messages."""
        client = self._get_client()
        try:
            stream = await client.chat.completions.create(
                model="deepseek-v4-flash",
                # model="deepseek-v4-pro",  # experiment: plans/synastry-before-batching.md
                messages=messages,
                temperature=0.3,
                max_tokens=self.MAX_TOKENS,
                timeout=500,
                stream=True,
            )
            # Same silent-truncation guard as generate() (finish_reason='length'
            # means max_tokens cut the text mid-sentence) — in streaming mode
            # finish_reason and usage only arrive attached to the final chunk(s),
            # so both are tracked across the whole loop instead of read off one
            # response.
            finish_reason = None
            completion_tokens = "?"
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                if chunk.choices and chunk.choices[0].finish_reason:
                    finish_reason = chunk.choices[0].finish_reason
                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    completion_tokens = getattr(usage, "completion_tokens", "?")
            print(
                f"[DeepSeekAdapter] finish_reason={finish_reason}"
                f" completion_tokens={completion_tokens}"
                f" max_tokens={self.MAX_TOKENS}"
            )
        except Exception as e:
            yield f"Error: {str(e)}"

class OpenRouterAdapter(LLMAdapter):
    """OpenRouter adapter: OpenAI-compatible API, any model by slug"""

    # Same ceiling and rationale as DeepSeekAdapter.MAX_TOKENS above.
    MAX_TOKENS = 45000

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
                max_tokens=self.MAX_TOKENS,
                timeout=500,
            )
            choice = response.choices[0]
            usage = getattr(response, "usage", None)
            print(
                f"[OpenRouterAdapter] finish_reason={choice.finish_reason}"
                f" completion_tokens={getattr(usage, 'completion_tokens', '?')}"
                f" max_tokens={self.MAX_TOKENS}"
            )
            return choice.message.content
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
                timeout=500,
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

# Fallback model for when the primary provider fails: routed through
# OpenRouter (own key/quota, separate from any direct OpenAI account) rather
# than OpenAI directly, since this account's direct OpenAI key is shared with
# other unrelated projects and already runs into rate limits there.
FALLBACK_MODEL = "openai/gpt-5.6-luna"


class FallbackAdapterWrapper(LLMAdapter):
    """Wraps a primary adapter with a fallback adapter used whenever the
    primary either raises or returns its own swallowed-error string (every
    adapter in this file catches exceptions internally and returns
    f"Error: {e}" instead of raising, so checking the string is the only way
    to detect a failed call)."""

    def __init__(self, primary: LLMAdapter, fallback: LLMAdapter):
        self.primary = primary
        self.fallback = fallback

    @staticmethod
    def _failed(result: str) -> bool:
        return not result or result.strip().startswith("Error:")

    @staticmethod
    def _log_fallback(result: str) -> None:
        print(f"[FallbackAdapterWrapper] primary failed ({result!r}) -> falling back to {FALLBACK_MODEL}")

    async def generate(self, prompt: str, language: str = "en") -> str:
        try:
            result = await self.primary.generate(prompt, language)
        except Exception as e:
            result = f"Error: {str(e)}"
        if self._failed(result):
            self._log_fallback(result)
            return await self.fallback.generate(prompt, language)
        return result

    async def generate_with_messages(self, messages: List[Dict[str, str]], language: str = "en") -> str:
        try:
            result = await self.primary.generate_with_messages(messages, language)
        except Exception as e:
            result = f"Error: {str(e)}"
        if self._failed(result):
            self._log_fallback(result)
            return await self.fallback.generate_with_messages(messages, language)
        return result

    async def generate_stream(self, prompt: str, language: str = "en") -> AsyncGenerator[str, None]:
        # Only recovers a failure on the very first chunk (connection refused,
        # rate limit, etc.) — once real tokens have already been streamed to
        # the caller, a mid-stream failure can't be undone, so it's left to
        # surface as-is rather than risk duplicating/garbling output.
        gen = self.primary.generate_stream(prompt, language)
        try:
            first_chunk = await gen.__anext__()
        except StopAsyncIteration:
            return
        except Exception as e:
            first_chunk = f"Error: {str(e)}"
        if self._failed(first_chunk):
            self._log_fallback(first_chunk)
            async for chunk in self.fallback.generate_stream(prompt, language):
                yield chunk
            return
        yield first_chunk
        async for chunk in gen:
            yield chunk

    async def generate_stream_with_messages(self, messages: List[Dict[str, str]], language: str = "en") -> AsyncGenerator[str, None]:
        gen = self.primary.generate_stream_with_messages(messages, language)
        try:
            first_chunk = await gen.__anext__()
        except StopAsyncIteration:
            return
        except Exception as e:
            first_chunk = f"Error: {str(e)}"
        if self._failed(first_chunk):
            self._log_fallback(first_chunk)
            async for chunk in self.fallback.generate_stream_with_messages(messages, language):
                yield chunk
            return
        yield first_chunk
        async for chunk in gen:
            yield chunk


def get_llm_adapter(provider: str = None, model: str = None) -> LLMAdapter:
    """Get the adapter for the given LLM provider.
    model is only used for openrouter (model slug)."""
    if provider is None:
        provider = settings.LLM_PROVIDER

    provider = provider.lower()

    if provider == 'openrouter':
        return OpenRouterAdapter(model)

    adapter_class = _adapters.get(provider, FallbackAdapter)
    adapter = adapter_class()

    # Wrap the production (deepseek) adapter with an OpenRouter fallback —
    # only if a key is configured, so behaviour is unchanged for anyone who
    # hasn't opted in.
    if provider == 'deepseek' and settings.OPENROUTER_API_KEY:
        adapter = FallbackAdapterWrapper(adapter, OpenRouterAdapter(FALLBACK_MODEL))

    return adapter


async def generate_analysis(
    prompt: str,
    language: str = "en",
    provider: str = None
) -> str:
    """Convenience function for generating an analysis"""
    adapter = get_llm_adapter(provider)
    return await adapter.generate(prompt, language)
