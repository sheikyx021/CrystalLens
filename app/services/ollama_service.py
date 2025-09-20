import requests
import json
import logging
from flask import current_app
from typing import List, Dict, Any
from app.models import get_setting

logger = logging.getLogger(__name__)

class OllamaService:
    """Service for interacting with Ollama local LLM API."""
    
    def __init__(self):
        """Initialize Ollama service."""
        self.api_url = current_app.config.get('OLLAMA_API_URL', 'http://localhost:11434')
        # Prefer DB setting for model if set by admin
        self.model = get_setting('OLLAMA_MODEL', current_app.config.get('OLLAMA_MODEL', 'llama2'))
        self.timeout = current_app.config.get('ANALYSIS_TIMEOUT', 300)
    
    def is_available(self):
        """Check if Ollama API is available."""
        try:
            response = requests.get(f"{self.api_url}/api/tags", timeout=10)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Ollama API not available: {str(e)}")
            return False
    
    def get_available_models(self):
        """Get list of available models."""
        try:
            response = requests.get(f"{self.api_url}/api/tags", timeout=10)
            if response.status_code == 200:
                data = response.json()
                return [model['name'] for model in data.get('models', [])]
            return []
        except Exception as e:
            logger.error(f"Error getting available models: {str(e)}")
            return []
    
    def analyze_social_media_posts(self, posts: List[Dict], employee_info: Dict, selected_checks: List[str] = None) -> Dict[str, Any]:
        """
        Analyze social media posts using Ollama LLM.
        
        Args:
            posts (List[Dict]): List of social media posts
            employee_info (Dict): Employee information
            
        Returns:
            Dict: Analysis results
        """
        if not posts:
            return self._empty_analysis_result("No posts to analyze")
        
        try:
            # Determine analysis mode (single vs staged)
            mode = (get_setting('ANALYSIS_MODE', 'single') or 'single').lower()
            if mode == 'single':
                prompt = self._build_single_prompt(posts, employee_info, selected_checks)
            else:
                # Stage 1: build evidence from posts (structured, per-post signals)
                ev_prompt = self._build_evidence_prompt(posts, employee_info)
                ev_text = self._generate_response(ev_prompt, temperature=0.2)
                evidence = self._parse_evidence_response(ev_text, len(posts))
                # If evidence failed to parse, try coercion once
                if not isinstance(evidence, dict) or 'posts' not in evidence:
                    try:
                        ev_coerced = self._coerce_to_json(ev_text)
                        if ev_coerced:
                            evidence = self._parse_evidence_response(ev_coerced, len(posts))
                    except Exception:
                        pass

                # Stage 2: final assessment based on evidence
                # If evidence extraction failed (no posts), fall back to direct analysis over raw posts
                if not evidence.get('posts'):
                    prompt = self._build_analysis_prompt(posts, employee_info)
                else:
                    prompt = self._build_analysis_prompt_from_evidence(evidence, employee_info)
            
            # Send request to Ollama (retry with temperature annealing)
            analysis_text = self._generate_response(prompt, temperature=0.2)
            
            # Parse the analysis response
            analysis_result = self._parse_analysis_response(analysis_text, len(posts))
            
            # If parse fell back to unstructured marker, try a JSON coercion retry once
            if analysis_result.get('summary', '').startswith('Unstructured analysis response') or \
               'unstructured' in (analysis_result.get('behavioral_insights') or '').lower():
                try:
                    coerced = self._coerce_to_json(analysis_text)
                    if coerced:
                        analysis_result = self._parse_analysis_response(coerced, len(posts))
                except Exception as _:
                    pass

            # Validate required fields; if missing or empty, attempt one repair pass
            if not self._is_result_complete(analysis_result):
                try:
                    repaired = self._repair_json(analysis_text)
                    if repaired:
                        analysis_result = self._parse_analysis_response(repaired, len(posts))
                except Exception:
                    pass
            
            # If many fields are unknown/empty, run a targeted completion pass
            if self._needs_completion(analysis_result):
                try:
                    completion_json = self._complete_missing_fields(evidence, analysis_result)
                    if completion_json:
                        improved = self._parse_analysis_response(completion_json, len(posts))
                        # Merge: prefer improved values when present/non-empty
                        analysis_result = self._merge_results(analysis_result, improved)
                except Exception:
                    pass

            logger.info(f"Successfully analyzed {len(posts)} posts for employee {employee_info.get('employee_id')}")
            return analysis_result
            
        except Exception as e:
            logger.error(f"Error analyzing posts: {str(e)}")
            return self._empty_analysis_result(f"Analysis failed: {str(e)}")
    
    def _build_analysis_prompt(self, posts: List[Dict], employee_info: Dict) -> str:
        """Build the analysis prompt for the LLM."""
        # Load assessment dimensions from settings (fallback to default list)
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

        # Prepare posts text
        posts_text = ""
        for i, post in enumerate(posts[:50], 1):  # Limit to first 50 posts to avoid token limits
            platform = post.get('platform', 'unknown')
            text = post.get('text', '')
            created_at = post.get('created_at', 'unknown')
            
            posts_text += f"\n--- Post {i} ({platform}) ---\n"
            posts_text += f"Date: {created_at}\n"
            posts_text += f"Content: {text}\n"
        
        # Build the comprehensive prompt
        prompt = f"""
You are an AI analyst specializing in behavioral assessment through social media analysis for government security screening. 

EMPLOYEE INFORMATION:
- Employee ID: {employee_info.get('employee_id', 'N/A')}
- Name: {employee_info.get('full_name', 'N/A')}
- Department: {employee_info.get('department', 'N/A')}
- Position: {employee_info.get('position', 'N/A')}

SOCIAL MEDIA POSTS TO ANALYZE:
{posts_text}

ANALYSIS REQUIREMENTS:
Provide a comprehensive behavioral and character analysis based strictly on the social media posts above. Your output must be evidence-driven.
For every judgement, include concise reasoning and cite specific posts using the format [Post <n> - <date>] with a short quoted snippet where applicable.
Avoid speculation that is not supported by the provided content.

1. RISK ASSESSMENT (0-100 scale):
   - 0-29: Low risk (minimal concerns)
   - 30-59: Medium risk (some concerns worth monitoring)
   - 60-79: High risk (significant concerns requiring attention)
   - 80-100: Critical risk (immediate attention required)
   Provide a brief rationale with citations.

2. CHARACTER ASSESSMENT:
   Analyze personality traits, values, and behavioral patterns evident in the posts. Include reasoning and citations to specific posts.

3. BEHAVIORAL INSIGHTS:
   Identify communication patterns, social interactions, and any concerning behaviors. Include reasoning and citations.

4. RED FLAGS:
   List any concerning content such as (each item should include a short reason and citation in-line):
   - Extremist views or hate speech
   - Substance abuse indicators
   - Financial distress
   - Security risks
   - Unprofessional behavior
   - Dishonesty or integrity issues

5. POSITIVE INDICATORS:
   List positive traits (each item should include a short reason and citation in-line) such as:
   - Professional conduct
   - Community involvement
   - Leadership qualities
   - Reliability indicators
   - Positive values

6. CONFIDENCE LEVEL (0-100):
   How confident are you in this assessment based on the available data?

7. SPECIFIC ASSESSMENTS:
   Provide focused assessments for the following dimensions if reasonably inferable from the posts. For each, include a brief justification and at least one citation when possible:
{chr(10).join([f"   - {k.replace('_', ' ')}" for k in selected_dims])}

FORMAT YOUR RESPONSE AS JSON:
{{
    "risk_score": <number 0-100>,
    "character_assessment": "<detailed character analysis with reasoning and citations>",
    "behavioral_insights": "<behavioral patterns and insights with reasoning and citations>",
    "red_flags": ["<concern> (reason: ..., citation: [Post n - date] 'quote')", "..."],
    "positive_indicators": ["<indicator> (reason: ..., citation: [Post n - date] 'quote')", "..."],
    "confidence_score": <number 0-100>,
    "summary": "<brief summary of key findings>",
    "assessments": {{
        "political_orientation": "<summary with reasoning and citation(s) if inferable, else 'unknown'>",
        "religious_orientation": "<summary with reasoning and citation(s) if inferable, else 'unknown'>",
        "violence_tendency": "<summary with reasoning and citation(s) if inferable, else 'unknown'>",
        "political_or_religious_affiliation": "<summary with reasoning and citation(s) if inferable, else 'unknown'>",
        "suitability_for_sensitive_positions": "<yes/no with short justification and citation(s) if inferable, else 'unknown'>",
        "discrimination_or_bias": "<summary about bias against class/gender/color with reasoning and citations, or 'unknown'>",
        "personal_issues_shared": "<summary of whether the person shares personal problems publicly with reasoning and citations, or 'unknown'>"
    }}
}}

Be objective, professional, and base your analysis strictly on observable content. Avoid speculation beyond what can be reasonably inferred from the posts.
"""
        
        # Debug (truncated) prompt logging
        try:
            logger.debug("Analysis prompt (first 200 chars): %s", prompt[:200])
        except Exception:
            pass
        return prompt

    def _build_single_prompt(self, posts: List[Dict], employee_info: Dict, selected_checks: List[str] = None) -> str:
        """Single-request mode: build one comprehensive prompt with optional section selection and prompt overrides."""
        # Selected checks mapping
        all_sections = ['risk','character','behavior','redflags','positive','assessments']
        checks = [c for c in (selected_checks or []) if c in all_sections]
        if not checks:
            checks = all_sections

        # Admin overrides
        extra = get_setting('PROMPT_EXTRA_INSTRUCTIONS', '') or ''
        ov = {
            'risk': get_setting('PROMPT_RISK', '') or '',
            'character': get_setting('PROMPT_CHARACTER', '') or '',
            'behavior': get_setting('PROMPT_BEHAVIOR', '') or '',
            'redflags': get_setting('PROMPT_REDFLAGS', '') or '',
            'positive': get_setting('PROMPT_POSITIVE', '') or '',
            'assessments': get_setting('PROMPT_ASSESSMENTS', '') or '',
        }

        # Assessments dimensions
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

        # Posts block
        posts_text = ""
        for i, post in enumerate(posts[:60], 1):
            platform = post.get('platform', 'unknown')
            text = post.get('text', '')
            created_at = post.get('created_at', 'unknown')
            posts_text += f"\n--- Post {i} ({platform}) ---\n"
            posts_text += f"Date: {created_at}\n"
            posts_text += f"Content: {text}\n"

        # Build prompt sections
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

    def _build_evidence_prompt(self, posts: List[Dict], employee_info: Dict) -> str:
        """Stage 1: Ask the model to extract structured evidence per post."""
        posts_text = ""
        for i, post in enumerate(posts[:80], 1):
            platform = post.get('platform', 'unknown')
            text = post.get('text', '')
            created_at = post.get('created_at', 'unknown')
            posts_text += f"\n--- Post {i} ({platform}) ---\n"
            posts_text += f"Date: {created_at}\n"
            posts_text += f"Content: {text}\n"
        prompt = (
            "You are extracting structured EVIDENCE from social media posts for a security assessment.\n"
            "Handle Arabic and English. Use exact quotes; do not fabricate.\n\n"
            "POSTS TO ANALYZE:\n" + posts_text + "\n\n"
            "Return ONLY JSON with this shape (keys required):\n"
            "{\n"
            "  \"posts\": [\n"
            "    {\n"
            "      \"index\": <number>,\n"
            "      \"date\": \"<date>\",\n"
            "      \"snippet\": \"<short exact quote>\",\n"
            "      \"languages\": [\"ar\", \"en\", ...],\n"
            "      \"sentiment\": \"negative|neutral|positive\",\n"
            "      \"topics\": [\"security\", \"politics\", ...],\n"
            "      \"risk_flags\": [\"extremism\", \"violence\", \"substance\", \"financial\", \"security_risk\", \"unprofessional\", \"dishonesty\"],\n"
            "      \"positive_signals\": [\"professionalism\", \"community\", \"leadership\", \"reliability\", \"positive_values\"]\n"
            "    }\n"
            "  ]\n"
            "}\n"
        )
        return prompt

    def _parse_evidence_response(self, response_text: str, posts_count: int) -> Dict[str, Any]:
        """Parse evidence JSON (stage 1)."""
        try:
            s = response_text.find('{')
            e = response_text.rfind('}') + 1
            if s != -1 and e > s:
                data = json.loads(response_text[s:e])
                # Basic normalization
                posts_ev = data.get('posts') or []
                if not isinstance(posts_ev, list):
                    posts_ev = []
                return {"posts": posts_ev}
        except Exception:
            pass
        # Fallback to empty evidence
        return {"posts": []}

    def _build_analysis_prompt_from_evidence(self, evidence: Dict[str, Any], employee_info: Dict) -> str:
        """Stage 2: Build assessment prompt using extracted evidence only."""
        # Load assessment dimensions
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

        # Summarize evidence into compact lines with indices and snippets
        lines = []
        for ev in (evidence.get('posts') or [])[:100]:
            try:
                idx = ev.get('index')
                date = ev.get('date', 'unknown')
                snip = ev.get('snippet', '')
                sent = ev.get('sentiment', 'neutral')
                topics = ', '.join(ev.get('topics') or [])
                rflags = ', '.join(ev.get('risk_flags') or [])
                psigs = ', '.join(ev.get('positive_signals') or [])
                lines.append(f"[Post {idx} - {date}] '{snip}' | sentiment={sent} | topics={topics} | risk_flags={rflags} | positive={psigs}")
            except Exception:
                continue

        evidence_block = "\n".join(lines)
        prompt = f"""
You are an AI analyst. Use ONLY the EVIDENCE below (do not invent). Provide detailed, cited reasoning.

EMPLOYEE:
- ID: {employee_info.get('employee_id', 'N/A')}
- Name: {employee_info.get('full_name', 'N/A')}
- Department: {employee_info.get('department', 'N/A')}
- Position: {employee_info.get('position', 'N/A')}

EVIDENCE (citations already normalized):
{evidence_block}

OUTPUT REQUIREMENTS:
- Evidence-driven, cite with [Post n - date] from the lines above.
- Arabic and English supported; include short exact quotes where helpful.
- If unknown, say 'unknown'.

Return ONLY JSON:
{{
  "risk_score": <number 0-100>,
  "character_assessment": "<detailed analysis with reasoning and citations>",
  "behavioral_insights": "<patterns with reasoning and citations>",
  "red_flags": ["<concern> (reason, citation)", "..."],
  "positive_indicators": ["<indicator> (reason, citation)", "..."],
  "confidence_score": <number 0-100>,
  "summary": "<brief summary>",
  "assessments": {{
    "political_orientation": "<summary with reasoning and citation(s) if inferable, else 'unknown'>",
    "religious_orientation": "<summary with reasoning and citation(s) if inferable, else 'unknown'>",
    "violence_tendency": "<summary with reasoning and citation(s) if inferable, else 'unknown'>",
    "political_or_religious_affiliation": "<summary with reasoning and citation(s) if inferable, else 'unknown'>",
    "suitability_for_sensitive_positions": "<yes/no with justification and citation(s) if inferable, else 'unknown'>"
  }}
}}
"""
        return prompt
    
    def _generate_response(self, prompt: str, temperature: float = 0.2) -> str:
        """Generate response from Ollama API."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,  # Lower temperature for more consistent, reasoned output
                "top_p": 0.9,
                "num_predict": 3072,  # Allow more room for detailed reasoning
                "num_ctx": 4096
            }
        }
        
        try:
            response = requests.post(
                f"{self.api_url}/api/generate",
                json=payload,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                text = result.get('response', '')
                # Simple heuristic: if response is very short, try one colder retry
                if len(text.strip()) < 50:
                    colder = self._raw_generate(prompt, temperature=max(0.1, temperature - 0.1))
                    if colder:
                        text = colder
                try:
                    logger.debug("Analysis response (first 200 chars): %s", text[:200])
                except Exception:
                    pass
                return text
            else:
                raise Exception(f"Ollama API error: {response.status_code} - {response.text}")
                
        except requests.exceptions.Timeout:
            raise Exception(f"Ollama API timeout after {self.timeout} seconds")
        except Exception as e:
            raise Exception(f"Ollama API request failed: {str(e)}")

    def _raw_generate(self, prompt: str, temperature: float) -> str:
        """One-off generation helper without retries, used internally for annealing."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "top_p": 0.9,
                "num_predict": 3072,
                "num_ctx": 4096
            }
        }
        try:
            response = requests.post(
                f"{self.api_url}/api/generate",
                json=payload,
                timeout=self.timeout
            )
            if response.status_code == 200:
                return response.json().get('response', '')
        except Exception:
            return ''
        return ''

    def _coerce_to_json(self, previous_text: str) -> str:
        """Attempt to coerce an unstructured response into strict JSON via a follow-up generation."""
        schema = {
            "risk_score": "number 0-100",
            "character_assessment": "string",
            "behavioral_insights": "string",
            "red_flags": ["string"],
            "positive_indicators": ["string"],
            "confidence_score": "number 0-100",
            "summary": "string",
            "assessments": {
                "political_orientation": "string",
                "religious_orientation": "string",
                "violence_tendency": "string",
                "political_or_religious_affiliation": "string",
                "suitability_for_sensitive_positions": "string"
            }
        }
        instruction = (
            "Return ONLY pure JSON matching this schema and keys exactly. "
            "Do not include markdown, explanations, or extra text. If a field cannot be inferred, set a reasonable default (" 
            "e.g., empty string, 0, or 'unknown').\n\n"
            f"Schema (informal): {json.dumps(schema)}\n\n"
            "Text to convert to JSON follows between <BEGIN> and <END>.\n"
            "<BEGIN>\n" + previous_text + "\n<END>"
        )
        return self._generate_response(instruction)

    def _repair_json(self, previous_text: str) -> str:
        """Ask the model to repair/complete missing fields into strict JSON using the same schema."""
        instruction = (
            "You previously produced an answer that was not fully compliant with the required JSON schema. "
            "Now output ONLY valid JSON with all required keys present. Do not include markdown or explanations. "
            "If data cannot be inferred, fill with defaults: 0, empty string, empty list, or 'unknown' as appropriate.\n\n"
            "Return the JSON now."
        )
        # Combine instruction with last text to help the model repair
        return self._generate_response(instruction + "\n\nPrevious text:\n" + previous_text, temperature=0.1)

    def _is_result_complete(self, result: Dict[str, Any]) -> bool:
        """Lightweight validation to ensure core fields are populated."""
        if not isinstance(result, dict):
            return False
        required_keys = [
            'risk_score', 'character_assessment', 'behavioral_insights',
            'red_flags', 'positive_indicators', 'confidence_score', 'summary'
        ]
        for k in required_keys:
            if k not in result:
                return False
        # Ensure lists are lists
        if not isinstance(result.get('red_flags'), list):
            return False
        if not isinstance(result.get('positive_indicators'), list):
            return False
        return True

    def _needs_completion(self, result: Dict[str, Any]) -> bool:
        """Heuristic to detect if too many fields are unknown/empty and warrant a completion pass."""
        if not isinstance(result, dict):
            return True
        unknown_markers = ['unknown', '', None]
        unknown_count = 0
        total_checks = 0
        for k in ['character_assessment', 'behavioral_insights', 'summary']:
            total_checks += 1
            v = result.get(k)
            if not v or (isinstance(v, str) and v.strip().lower() in unknown_markers):
                unknown_count += 1
        # Lists
        for k in ['red_flags', 'positive_indicators']:
            total_checks += 1
            v = result.get(k)
            if not isinstance(v, list) or len(v) == 0:
                unknown_count += 1
        # Assessments summary presence inferred inside behavioral_insights; still request completion
        return unknown_count >= max(2, total_checks // 2)

    def _complete_missing_fields(self, evidence: Dict[str, Any], current: Dict[str, Any]) -> str:
        """Ask the model to complete missing or 'unknown' fields only, using the extracted evidence."""
        # Build evidence block
        lines = []
        for ev in (evidence.get('posts') or [])[:120]:
            try:
                idx = ev.get('index')
                date = ev.get('date', 'unknown')
                snip = ev.get('snippet', '')
                sent = ev.get('sentiment', 'neutral')
                topics = ', '.join(ev.get('topics') or [])
                rflags = ', '.join(ev.get('risk_flags') or [])
                psigs = ', '.join(ev.get('positive_signals') or [])
                lines.append(f"[Post {idx} - {date}] '{snip}' | sentiment={sent} | topics={topics} | risk_flags={rflags} | positive={psigs}")
            except Exception:
                continue
        evidence_block = "\n".join(lines)

        # Determine missing pieces
        missing = {
            'character_assessment': not current.get('character_assessment'),
            'behavioral_insights': not current.get('behavioral_insights'),
            'red_flags': not current.get('red_flags'),
            'positive_indicators': not current.get('positive_indicators'),
            'summary': not current.get('summary'),
        }
        keys = [k for k, needed in missing.items() if needed]
        if not keys:
            return ''

        prompt = (
            "Using ONLY the EVIDENCE below, fill ONLY the missing fields listed. "
            "Return STRICT JSON with exactly those keys. Provide cited, reasoned content.\n\n"
            f"Missing keys: {json.dumps(keys)}\n\n"
            "EVIDENCE:\n" + evidence_block + "\n\n"
            "JSON shape example (values are placeholders):\n"
            "{\n"
            + ",\n".join([f'  "{k}": "value or list"' for k in keys]) + "\n"
            "}\n"
        )
        return self._generate_response(prompt, temperature=0.15)

    def _merge_results(self, base: Dict[str, Any], add: Dict[str, Any]) -> Dict[str, Any]:
        """Merge two analysis dicts, preferring non-empty values from 'add'."""
        out = dict(base)
        for k, v in add.items():
            if v in (None, '', [], {}):
                continue
            if isinstance(v, list):
                if not isinstance(out.get(k), list) or not out.get(k):
                    out[k] = v
            else:
                if not out.get(k):
                    out[k] = v
        return out
    
    def _parse_analysis_response(self, response_text: str, posts_count: int) -> Dict[str, Any]:
        """Parse the LLM response into structured analysis result."""
        try:
            # Try to extract JSON from the response
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            
            if json_start != -1 and json_end > json_start:
                json_text = response_text[json_start:json_end]
                analysis_data = json.loads(json_text)
                
                # Validate and clean the data
                result = {
                    'risk_score': self._validate_score(analysis_data.get('risk_score')),
                    'character_assessment': analysis_data.get('character_assessment', ''),
                    'behavioral_insights': analysis_data.get('behavioral_insights', ''),
                    'red_flags': analysis_data.get('red_flags', []),
                    'positive_indicators': analysis_data.get('positive_indicators', []),
                    'confidence_score': self._validate_score(analysis_data.get('confidence_score')),
                    'summary': analysis_data.get('summary', ''),
                    'posts_analyzed': posts_count,
                    'analysis_model': self.model,
                    'raw_response': response_text
                }
                # If assessments object exists, merge a readable summary into behavioral_insights
                assessments = analysis_data.get('assessments') or {}
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
            else:
                # Fallback: parse unstructured response
                return self._parse_unstructured_response(response_text, posts_count)
                
        except json.JSONDecodeError:
            # Fallback: parse unstructured response
            return self._parse_unstructured_response(response_text, posts_count)
        except Exception as e:
            logger.error(f"Error parsing analysis response: {str(e)}")
            return self._empty_analysis_result(f"Failed to parse analysis: {str(e)}")
    
    def _parse_unstructured_response(self, response_text: str, posts_count: int) -> Dict[str, Any]:
        """Parse unstructured response as fallback."""
        return {
            'risk_score': 50.0,  # Default medium risk
            'character_assessment': response_text[:1000],  # First 1000 chars
            'behavioral_insights': 'Analysis completed but response format was unstructured.',
            'red_flags': [],
            'positive_indicators': [],
            'confidence_score': 30.0,  # Low confidence for unstructured
            'summary': 'Unstructured analysis response received.',
            'posts_analyzed': posts_count,
            'analysis_model': self.model,
            'raw_response': response_text
        }
    
    def _validate_score(self, score) -> float:
        """Validate and normalize score to 0-100 range."""
        try:
            score = float(score)
            return max(0.0, min(100.0, score))
        except (TypeError, ValueError):
            return 50.0  # Default to medium score if invalid
    
    def _empty_analysis_result(self, error_message: str) -> Dict[str, Any]:
        """Return empty analysis result with error message."""
        return {
            'risk_score': None,
            'character_assessment': f"Analysis could not be completed: {error_message}",
            'behavioral_insights': '',
            'red_flags': [],
            'positive_indicators': [],
            'confidence_score': 0.0,
            'summary': f"Analysis failed: {error_message}",
            'posts_analyzed': 0,
            'analysis_model': self.model,
            'raw_response': error_message
        }
    
    def test_connection(self) -> Dict[str, Any]:
        """Test connection to Ollama API."""
        try:
            # Test basic connectivity
            if not self.is_available():
                return {
                    'status': 'error',
                    'message': 'Ollama API is not available'
                }
            
            # Test model availability
            models = self.get_available_models()
            if self.model not in models:
                return {
                    'status': 'warning',
                    'message': f'Configured model "{self.model}" not found. Available models: {", ".join(models)}'
                }
            
            # Test simple generation
            test_prompt = "Respond with 'OK' if you can process this request."
            response = self._generate_response(test_prompt)
            
            return {
                'status': 'success',
                'message': f'Ollama API is working with model "{self.model}"',
                'available_models': models,
                'test_response': response[:100]  # First 100 chars
            }
            
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Ollama API test failed: {str(e)}'
            }
