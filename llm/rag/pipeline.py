# rag/pipeline.py
from openai import OpenAI
from rag.config import LLM_BASE_URL, LLM_MODEL, LLM_API_KEY
from rag.retriever import Retriever
from rag.prompt_builder import build_prompt


class RAGPipeline:
    def __init__(self):
        self._retriever = Retriever()
        self._client = OpenAI(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
        )

    def query(self, question: str) -> str:
        chunks = self._retriever.retrieve(question)
        system_prompt, user_message = build_prompt(chunks, question)
        response = self._client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message},
            ],
            temperature=0.3,
            max_tokens=512,
        )
        return response.choices[0].message.content.strip()
