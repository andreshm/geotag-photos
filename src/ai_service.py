"""ai_service.py — AI Vision Geolocation Predictor supporting Local Ollama, Gemini, and OpenAI."""

from __future__ import annotations

import base64
import json
import logging
import re
import urllib.request
import urllib.error
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Optional, Any
from PIL import Image

log = logging.getLogger(__name__)

# Settings Keys
SETTINGS_AI_PROVIDER = "ai/provider"       # "ollama", "gemini", "openai"
SETTINGS_OLLAMA_URL   = "ai/ollama_url"     # default "http://localhost:11434"
SETTINGS_OLLAMA_MODEL = "ai/ollama_model"   # default "llama3.2-vision"
SETTINGS_GEMINI_KEY   = "ai/gemini_key"
SETTINGS_GEMINI_MODEL = "ai/gemini_model"   # default "gemini-1.5-flash"
SETTINGS_OPENAI_KEY   = "ai/openai_key"
SETTINGS_OPENAI_MODEL = "ai/openai_model"   # default "gpt-4o-mini"


@dataclass
class AIPredictionResult:
    location_name: str
    latitude: float
    longitude: float
    confidence: str  # "high", "medium", "low"
    reasoning: str
    provider_used: str
    model_used: str
    raw_response: str = ""


class AIService:
    """Service to query vision models for intelligent image geolocation prediction."""

    @staticmethod
    def encode_image_base64(image_path: Path, max_dim: int = 1280, quality: int = 85) -> str:
        """Loads and pre-scales image to a compact JPEG base64 payload for fast API transmission."""
        with Image.open(image_path) as img:
            # Handle RGBA / P modes
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGB")
            
            # Scale down if larger than max_dim
            w, h = img.size
            if max(w, h) > max_dim:
                scale = max_dim / max(w, h)
                new_size = (int(w * scale), int(h * scale))
                img = img.resize(new_size, Image.Resampling.LANCZOS)

            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=quality)
            return base64.b64encode(buffer.getvalue()).decode("utf-8")

    @staticmethod
    def build_prompt(
        user_clues: str = "",
        same_day_anchors: Optional[list[dict]] = None,
        date_str: str = "",
        camera_model: str = "",
    ) -> str:
        """Constructs a rich contextual prompt with same-day GPS anchors and clues."""
        prompt_parts = [
            "You are an expert geolocation investigator and vision analyst.",
            "Analyze the visual features of this image (architecture, landmarks, terrain, vegetation, signs, text, road markings, lighting, culture) to determine where on Earth it was taken.",
        ]

        if date_str:
            prompt_parts.append(f"\nPhoto Timestamp: {date_str}")

        if camera_model:
            prompt_parts.append(f"Camera Device: {camera_model}")

        if user_clues and user_clues.strip():
            prompt_parts.append(f"\nUSER CLUES / MEMORY:\n\"{user_clues.strip()}\"")

        if same_day_anchors:
            anchor_lines = []
            for a in same_day_anchors[:8]:
                time_str = a.get("time", "")
                lat = a.get("lat")
                lon = a.get("lon")
                name = a.get("name", "")
                line = f"- Time {time_str}: ({lat:.5f}, {lon:.5f})"
                if name:
                    line += f" near {name}"
                anchor_lines.append(line)

            prompt_parts.append(
                f"\nCONTEXTUAL SAME-DAY GPS ANCHORS:\n"
                f"The user took other photos on the exact same date at these verified coordinates:\n"
                + "\n".join(anchor_lines) + "\n"
                f"Use these same-day anchor locations as strong regional context (e.g. same trip, city, or route), "
                f"unless the visual scenery clearly indicates a different place."
            )

        prompt_parts.append(
            "\nREQUIRED OUTPUT FORMAT:\n"
            "You MUST return ONLY a valid JSON object (no markdown, no surrounding text) matching this exact schema:\n"
            "{\n"
            '  "location_name": "Specific Landmark, City, State/Province, Country",\n'
            '  "latitude": 43.7731,\n'
            '  "longitude": 11.2560,\n'
            '  "confidence": "high" | "medium" | "low",\n'
            '  "reasoning": "Detailed visual explanation of landmarks, architecture, signs, or same-day context identified."\n'
            "}\n"
            "Provide the most accurate GPS coordinates possible (latitude between -90 and 90, longitude between -180 and 180)."
        )

        return "\n".join(prompt_parts)

    @classmethod
    def parse_json_response(cls, response_text: str, provider: str, model: str) -> AIPredictionResult:
        """Extracts and validates structured JSON prediction from LLM response text."""
        raw = response_text.strip()
        if not raw:
            raise ValueError(
                f"The model '{model}' returned an empty response.\n\n"
                f"⚠️ Please ensure '{model}' is a Multimodal Vision model (such as llama3.2-vision, llava, minicpm-v, or qwen2.5-vl).\n"
                f"Text-only models (like qwen2.5, llama3, or mistral) cannot see or process images."
            )

        # 1. Strip thinking tags <think>...</think> if present (DeepSeek-R1 / Qwen reasoning models)
        cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

        # 2. Strip markdown code blocks
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

        # 3. Try standard JSON extraction
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            json_candidate = match.group(0)
            try:
                data = json.loads(json_candidate)
                lat = float(data.get("latitude", 0.0))
                lon = float(data.get("longitude", 0.0))
                loc_name = str(data.get("location_name", "Unknown Location")).strip()
                confidence = str(data.get("confidence", "medium")).lower().strip()
                if confidence not in ("high", "medium", "low"):
                    confidence = "medium"
                reasoning = str(data.get("reasoning", "")).strip()

                if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0 and (lat != 0.0 or lon != 0.0):
                    return AIPredictionResult(
                        location_name=loc_name,
                        latitude=lat,
                        longitude=lon,
                        confidence=confidence,
                        reasoning=reasoning,
                        provider_used=provider,
                        model_used=model,
                        raw_response=response_text,
                    )
            except Exception:
                pass

        # 4. Fallback: Regex key extraction for malformed JSON or unescaped quotes
        lat_m = re.search(r'["\']?latitude["\']?\s*:\s*([+-]?\d+(?:\.\d+)?)', cleaned, re.IGNORECASE)
        lon_m = re.search(r'["\']?longitude["\']?\s*:\s*([+-]?\d+(?:\.\d+)?)', cleaned, re.IGNORECASE)
        loc_m = re.search(r'["\']?location(?:_name)?["\']?\s*:\s*["\']([^"\']+)["\']', cleaned, re.IGNORECASE)
        res_m = re.search(r'["\']?reasoning["\']?\s*:\s*["\']([^"\']+)["\']', cleaned, re.IGNORECASE)

        if lat_m and lon_m:
            lat = float(lat_m.group(1))
            lon = float(lon_m.group(1))
            if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                loc_name = loc_m.group(1).strip() if loc_m else "Predicted Location"
                reasoning = res_m.group(1).strip() if res_m else cleaned[:400]
                return AIPredictionResult(
                    location_name=loc_name,
                    latitude=lat,
                    longitude=lon,
                    confidence="medium",
                    reasoning=reasoning,
                    provider_used=provider,
                    model_used=model,
                    raw_response=response_text,
                )

        # 5. Fallback: Raw Coordinate extraction (e.g. "43.7696, 11.2558")
        coord_m = re.search(r'([+-]?\d{1,2}\.\d+)\s*,\s*([+-]?\d{1,3}\.\d+)', cleaned)
        if coord_m:
            lat = float(coord_m.group(1))
            lon = float(coord_m.group(2))
            if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                return AIPredictionResult(
                    location_name="Estimated Location",
                    latitude=lat,
                    longitude=lon,
                    confidence="low",
                    reasoning=cleaned[:400],
                    provider_used=provider,
                    model_used=model,
                    raw_response=response_text,
                )

        raise ValueError(
            f"Could not extract valid GPS coordinates from model response.\n\n"
            f"Model Response:\n{raw[:300]}..."
        )

    # ── Provider 1: Local Ollama ──────────────────────────────────────────────

    @classmethod
    def fetch_ollama_models(cls, server_url: str = "http://localhost:11434") -> list[str]:
        """Fetches list of installed models from local Ollama instance."""
        url = server_url.rstrip("/") + "/api/tags"
        req = urllib.request.Request(url, headers={"User-Agent": "GeoTagStudioPRO/2.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m["name"] for m in data.get("models", [])]
            return models

    @classmethod
    def predict_with_ollama(
        cls,
        image_b64: str,
        prompt: str,
        server_url: str = "http://localhost:11434",
        model: str = "llama3.2-vision",
        timeout: int = 120,
    ) -> AIPredictionResult:
        """Sends image and prompt to local Ollama vision model."""
        url = server_url.rstrip("/") + "/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "images": [image_b64],
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.2,
            },
        }

        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={"Content-Type": "application/json", "User-Agent": "GeoTagStudioPRO/2.0"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
                response_text = res_json.get("response", "").strip()

            # If response was empty with format="json", retry once without format constraint
            if not response_text:
                payload.pop("format", None)
                data_bytes = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    url,
                    data=data_bytes,
                    headers={"Content-Type": "application/json", "User-Agent": "GeoTagStudioPRO/2.0"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    res_json = json.loads(resp.read().decode("utf-8"))
                    response_text = res_json.get("response", "").strip()

            return cls.parse_json_response(response_text, "Ollama (Local)", model)
        except urllib.error.URLError as exc:
            raise ConnectionError(
                f"Could not connect to Ollama at {server_url}. Ensure Ollama is running (`ollama serve`). Details: {exc}"
            )

    # ── Provider 2: Google Gemini ─────────────────────────────────────────────

    @classmethod
    def predict_with_gemini(
        cls,
        image_b64: str,
        prompt: str,
        api_key: str,
        model: str = "gemini-1.5-flash",
        timeout: int = 60,
    ) -> AIPredictionResult:
        """Sends image and prompt to Google Gemini Vision API."""
        if not api_key or not api_key.strip():
            raise ValueError("Google Gemini API Key is missing. Configure it in ⚙️ AI Settings.")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key.strip()}"
        
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": image_b64,
                            }
                        },
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "response_mime_type": "application/json",
            },
        }

        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
                candidates = res_json.get("candidates", [])
                if not candidates:
                    raise ValueError(f"Gemini returned no candidates: {res_json}")
                text = candidates[0]["content"]["parts"][0]["text"]
                return cls.parse_json_response(text, "Google Gemini", model)
        except urllib.error.HTTPError as exc:
            err_msg = exc.read().decode("utf-8", errors="ignore")
            raise ConnectionError(f"Gemini API Error ({exc.code}): {err_msg}")

    # ── Provider 3: OpenAI ────────────────────────────────────────────────────

    @classmethod
    def predict_with_openai(
        cls,
        image_b64: str,
        prompt: str,
        api_key: str,
        model: str = "gpt-4o-mini",
        timeout: int = 60,
    ) -> AIPredictionResult:
        """Sends image and prompt to OpenAI GPT-4o Vision API."""
        if not api_key or not api_key.strip():
            raise ValueError("OpenAI API Key is missing. Configure it in ⚙️ AI Settings.")

        url = "https://api.openai.com/v1/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_b64}"
                            },
                        },
                    ],
                }
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }

        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key.strip()}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
                choices = res_json.get("choices", [])
                if not choices:
                    raise ValueError(f"OpenAI returned no choices: {res_json}")
                text = choices[0]["message"]["content"]
                return cls.parse_json_response(text, "OpenAI", model)
        except urllib.error.HTTPError as exc:
            err_msg = exc.read().decode("utf-8", errors="ignore")
            raise ConnectionError(f"OpenAI API Error ({exc.code}): {err_msg}")
