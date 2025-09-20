import os
import json
import logging
from typing import List, Dict, Any
import requests
from flask import current_app
from app.models import get_setting

logger = logging.getLogger(__name__)

class GeminiService:
    """Service to interact with Google Gemini (gemini-2.0-flash) for fast single-request analysis."""

    def __init__(self):
        self.api_key = get_setting('GOOGLE_API_KEY', os.environ.get('GOOGLE_API_KEY'))
        if not self.api_key:
            raise ValueError('GOOGLE_API_KEY not configured')
        # Model name (allow override via settings later if needed)
        self.model = current_app.config.get('GEMINI_MODEL', 'gemini-2.0-flash')
        # Endpoint
        self.api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        # Timeouts
        self.timeout = current_app.config.get('ANALYSIS_TIMEOUT', 300)

    def analyze_social_media_posts(self, posts: List[Dict], employee_info: Dict, selected_checks: List[str] = None) -> Dict[str, Any]:
        prompt = self._build_single_prompt(posts, employee_info, selected_checks)
        response_text = self._generate_response(prompt)
        # Try to parse JSON from Gemini response
        try:
            start = response_text.find('{')
            end = response_text.rfind('}') + 1
            if start != -1 and end > start:
                json_text = response_text[start:end]
                data = json.loads(json_text)
                return self._normalize_result(data, len(posts))
        except Exception as e:
            logger.error(f"Gemini parse error: {e}")
        # Fallback
        return {
            'risk_score': None,
            'character_assessment': 'Analysis could not parse JSON response from Gemini.',
            'behavioral_insights': '',
            'red_flags': [],
            'positive_indicators': [],
            'confidence_score': 0.0,
            'summary': 'Unstructured analysis response received.',
            'posts_analyzed': len(posts),
            'analysis_model': self.model,
            'raw_response': response_text,
        }

    def _build_single_prompt(self, posts: List[Dict], employee_info: Dict, selected_checks: List[str] = None) -> str:
        all_sections = ['risk','character','behavior','redflags','positive','assessments']
        checks = [c for c in (selected_checks or []) if c in all_sections]
        if not checks:
            checks = all_sections

        extra = get_setting('PROMPT_EXTRA_INSTRUCTIONS', '') or ''
        ov = {
            'risk': get_setting('PROMPT_RISK', '') or '',
            'character': get_setting('PROMPT_CHARACTER', '') or '',
            'behavior': get_setting('PROMPT_BEHAVIOR', '') or '',
            'redflags': get_setting('PROMPT_REDFLAGS', '') or '',
            'positive': get_setting('PROMPT_POSITIVE', '') or '',
            'assessments': get_setting('PROMPT_ASSESSMENTS', '') or '',
        }

        default_dims = [
            'political_orientation',
            'religious_orientation',
            'violence_tendency',
            'political_or_religious_affiliation',
            'suitability_for_sensitive_positions',
        ]
        try:
            dims_setting = get_setting('ASSESSMENT_DIMENSIONS', None)
            selected_dims = json.loads(dims_setting) if dims_setting else default_dims
        except Exception:
            selected_dims = default_dims

        posts_text = ''
        for i, post in enumerate(posts[:60], 1):
            platform = post.get('platform', 'unknown')
            text = post.get('text', '')
            created_at = post.get('created_at', 'unknown')
            posts_text += f"\n--- Post {i} ({platform}) ---\n"
            posts_text += f"Date: {created_at}\n"
            posts_text += f"Content: {text}\n"

        sections_text = []
        if 'risk' in checks:
            sections_text.append("1. RISK ASSESSMENT: Provide a 0-100 score with concise reasoning and citations. " + ov['risk'])
        if 'character' in checks:
            sections_text.append("2. CHARACTER ASSESSMENT: Personality traits, values, patterns; include reasoning & citations. " + ov['character'])
        if 'behavior' in checks:
            sections_text.append("3. BEHAVIORAL INSIGHTS: Communication patterns and concerning behaviors; include reasoning & citations. " + ov['behavior'])
        if 'redflags' in checks:
            sections_text.append("4. RED FLAGS: List items with reason and citation. " + ov['redflags'])
        if 'positive' in checks:
            sections_text.append("5. POSITIVE INDICATORS: List items with reason and citation. " + ov['positive'])
        if 'assessments' in checks:
            bullet_dims = "\n".join([f"   - {k.replace('_',' ')}" for k in selected_dims])
            sections_text.append("6. SPECIFIC ASSESSMENTS: For each dimension, add justification and citation(s):\n" + bullet_dims + "\n" + ov['assessments'])

        sections_block = "\n\n".join(sections_text)

        prompt = f"""
You are an AI analyst. Handle Arabic and English. Use exact quotes; do not fabricate. Avoid speculation beyond evidence.

EMPLOYEE INFORMATION:
- Employee ID: {employee_info.get('employee_id', 'N/A')}
- Name: {employee_info.get('full_name', 'N/A')}
- Department: {employee_info.get('department', 'N/A')}
- Position: {employee_info.get('position', 'N/A')}

SOCIAL MEDIA POSTS:
{posts_text}

ANALYSIS REQUIREMENTS:
{sections_block}

EXTRA INSTRUCTIONS (admin): {extra}

Return ONLY JSON:
{{
  "risk_score": <number 0-100>,
  "character_assessment": "<text>",
  "behavioral_insights": "<text>",
  "red_flags": ["<item (reason, citation)>", "..."],
  "positive_indicators": ["<item (reason, citation)>", "..."],
  "confidence_score": <number 0-100>,
  "summary": "<brief summary>",
  "assessments": {{
    "political_orientation": "<summary or 'unknown'>",
    "religious_orientation": "<summary or 'unknown'>",
    "violence_tendency": "<summary or 'unknown'>",
    "political_or_religious_affiliation": "<summary or 'unknown'>",
    "suitability_for_sensitive_positions": "<yes/no with justification or 'unknown'>",
    "discrimination_or_bias": "<summary or 'unknown'>",
    "personal_issues_shared": "<summary or 'unknown'>"
  }}
}}
"""
        return prompt

    def _generate_response(self, prompt: str) -> str:
        headers = {"Content-Type": "application/json"}
        params = {"key": self.api_key}
        # Ask for JSON output explicitly
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "topP": 0.9,
                "maxOutputTokens": 3072,
                "responseMimeType": "application/json"
            }
        }
        try:
            resp = requests.post(self.api_url, headers=headers, params=params, json=payload, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                # Newer API returns candidates with content.parts[0].text
                text = ''
                try:
                    candidates = data.get('candidates', [])
                    if candidates:
                        parts = candidates[0].get('content', {}).get('parts', [])
                        if parts:
                            text = parts[0].get('text', '')
                except Exception:
                    text = resp.text
                return text or resp.text
            else:
                raise Exception(f"Gemini API error: {resp.status_code} - {resp.text}")
        except requests.exceptions.Timeout:
            raise Exception(f"Gemini API timeout after {self.timeout} seconds")
        except Exception as e:
            raise Exception(f"Gemini API request failed: {str(e)}")

    def _normalize_result(self, data: Dict[str, Any], posts_count: int) -> Dict[str, Any]:
        result = {
            'risk_score': data.get('risk_score'),
            'character_assessment': data.get('character_assessment', ''),
            'behavioral_insights': data.get('behavioral_insights', ''),
            'red_flags': data.get('red_flags', []) or [],
            'positive_indicators': data.get('positive_indicators', []) or [],
            'confidence_score': data.get('confidence_score'),
            'summary': data.get('summary', ''),
            'posts_analyzed': posts_count,
            'analysis_model': self.model,
            'raw_response': json.dumps(data)[:4000],
        }
        # Merge assessments into behavioral_insights for rendering in Specific Assessments panel
        assessments = data.get('assessments') or {}
        if isinstance(assessments, dict) and assessments:
            parts = []
            mapping = {
                'political_orientation': 'Political orientation',
                'religious_orientation': 'Religious orientation',
                'violence_tendency': 'Violence tendency',
                'political_or_religious_affiliation': 'Political/Religious affiliation',
                'suitability_for_sensitive_positions': 'Suitability for sensitive positions',
                'discrimination_or_bias': 'Bias against class/gender/color',
                'personal_issues_shared': 'Personal problems shared publicly',
            }
            for k, label in mapping.items():
                v = assessments.get(k)
                if v:
                    parts.append(f"{label}: {v}")
            if parts:
                joined = "\n".join(parts)
                if result['behavioral_insights']:
                    result['behavioral_insights'] += "\n\nAssessments:\n" + joined
                else:
                    result['behavioral_insights'] = "Assessments:\n" + joined
        return result

    def test_connection(self) -> Dict[str, Any]:
        """Quick connectivity and permissions test for Gemini API."""
        try:
            prompt = "Respond with JSON: {\"ok\": true}"
            text = self._generate_response(prompt)
            if '"ok": true' in text:
                return {
                    'status': 'success',
                    'message': f'Gemini API is working with model "{self.model}"'
                }
            return {
                'status': 'warning',
                'message': 'Gemini API responded but JSON check did not match.'
            }
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Gemini API test failed: {str(e)}'
            }
