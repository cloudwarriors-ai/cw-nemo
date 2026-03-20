import os
import logging
import json
from typing import Optional, Dict, Any, List
from openai import OpenAI
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)


# Pydantic models for structured validation output
class ScreenshotAssessment(BaseModel):
    """Assessment of screenshot quality and relevance"""
    url: str
    is_relevant: bool
    shows_issue: bool
    quality: str  # "excellent", "good", "poor", "unclear"
    feedback: str


class IssueValidationResult(BaseModel):
    """Structured validation result from GPT-4 Vision"""
    score: int = Field(ge=0, le=100, description="Overall quality score")
    is_actionable: bool = Field(description="Whether issue is actionable by developers")
    severity: str = Field(description="pass, needs_improvement, or insufficient")

    # Detailed breakdown
    clarity_score: int = Field(ge=0, le=10)
    completeness_score: int = Field(ge=0, le=10)
    actionability_score: int = Field(ge=0, le=10)
    screenshot_score: int = Field(ge=0, le=10)
    reproducibility_score: int = Field(ge=0, le=10)

    # Specific feedback
    missing_info: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)
    screenshot_assessments: List[ScreenshotAssessment] = Field(default_factory=list)

    # Examples
    better_title: Optional[str] = None
    better_description: Optional[str] = None

    # Category detection
    detected_type: str = Field(default="bug")  # bug, feature, question, improvement, other
    confidence: float = Field(ge=0, le=1, default=0.5)

class LLMBot:
    def __init__(self):
        self.api_key = os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set")
            
        self.client = OpenAI(api_key=self.api_key)
        self.model = os.getenv('OPENAI_MODEL', 'gpt-4')
        self.max_tokens = int(os.getenv('OPENAI_MAX_TOKENS', '1000'))
        self.temperature = float(os.getenv('OPENAI_TEMPERATURE', '0.7'))
        
    def generate_response(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Generate a response using the LLM"""
        try:
            logger.info(f"Generating LLM response for prompt: {prompt[:100]}...")
            logger.info(f"Context: {context}")
            
            messages = self._build_messages(prompt, context)
            logger.debug(f"Built messages for LLM: {json.dumps(messages, indent=2)}")
            
            logger.info(f"Making API call to OpenAI with model: {self.model}")
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            logger.debug(f"Raw OpenAI response: {response.model_dump_json()}")
            
            result = response.choices[0].message.content
            logger.info(f"Generated response ({len(result)} chars): {result[:100]}...")
            return result
            
        except Exception as e:
            logger.error(f"OpenAI API error: {str(e)}", exc_info=True)
            return f"Sorry, there was an error with the AI service: {str(e)}"
            
    def _build_messages(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> list:
        """Build the messages list for the OpenAI API"""
        messages = []
        
        # Add system message
        messages.append({
            "role": "system",
            "content": "You are a helpful AI assistant that specializes in understanding GitHub events and providing insights about code and development activities."
        })
        
        # Add context if provided
        if context:
            context_message = "Context:\n"
            if 'repository' in context:
                context_message += f"- Repository: {context['repository']}\n"
            if 'event_type' in context:
                context_message += f"- Event Type: {context['event_type']}\n"
            if 'actor' in context:
                context_message += f"- Actor: {context['actor']}\n"
            if 'action' in context:
                context_message += f"- Action: {context['action']}\n"
            if 'title' in context:
                context_message += f"- Title: {context['title']}\n"
                
            messages.append({
                "role": "system",
                "content": context_message
            })
                
        # Add the user's prompt
        messages.append({
            "role": "user",
            "content": prompt
        })
        
        return messages
    
    def analyze_pr(self, title: str, description: str, changes: Optional[str] = None) -> str:
        """Analyze a pull request and provide insights"""
        prompt = f"""Analyze this pull request:
Title: {title}
Description: {description}
"""
        if changes:
            prompt += f"\nChanges:\n{changes}"
            
        prompt += "\n\nPlease provide:\n1. A brief summary\n2. Potential impact\n3. Suggested review focus areas"
        
        return self.generate_response(prompt, {"event_type": "pull_request"})
    
    def analyze_issue(self, title: str, body: str) -> str:
        """Analyze an issue and provide insights"""
        prompt = f"""Analyze this issue:
Title: {title}
Description: {body}

Please provide:
1. Issue category (bug, feature request, question, etc.)
2. Priority assessment
3. Suggested next steps"""
        
        return self.generate_response(prompt, {"event_type": "issue"})
    
    def analyze_commit(self, message: str, changes: str) -> str:
        """Analyze a commit and provide insights"""
        prompt = f"""Analyze this commit:
Message: {message}
Changes: {changes}

Please provide:
1. Impact assessment
2. Potential risks
3. Suggested testing areas"""

        return self.generate_response(prompt, {"event_type": "push"})

    async def validate_issue_with_vision(
        self,
        title: str,
        description: str,
        screenshot_urls: List[str],
        reproduction_steps: str,
        environment: str,
        expected_behavior: str,
        actual_behavior: str,
        application_name: str
    ) -> IssueValidationResult:
        """
        Validate issue using GPT-4 Vision to analyze screenshots.

        Returns structured validation with:
        - Overall score (0-100)
        - Missing information list
        - Specific suggestions
        - Screenshot quality assessment
        - Actionability verdict
        """
        logger.info(f"Validating issue with vision: '{title[:50]}...'")

        # Build validation system prompt
        system_prompt = """You are an expert software quality analyst reviewing GitHub issues.

Your job is to assess whether an issue provides enough information for a developer to:
1. Understand what's wrong
2. Reproduce the problem
3. Fix the issue confidently

Score each dimension 0-10:
- **Clarity**: Can a developer understand what's wrong?
- **Completeness**: Is all critical info provided?
- **Actionability**: Can someone fix this based on the info?
- **Screenshot Quality**: Do images show the actual problem?
- **Reproducibility**: Can someone recreate the issue?

Overall score = sum of dimensions × 2 (max 100)

**Severity levels:**
- **pass** (70-100): Excellent or good - ready to work on
- **needs_improvement** (40-69): Missing some details but fixable
- **insufficient** (<40): Too vague, would be immediately closed

Be strict but constructive. Suggest specific improvements."""

        # Build user prompt with all fields
        user_prompt = f"""Validate this GitHub issue for **{application_name}**:

**TITLE:** {title}

**DESCRIPTION:** {description or "(empty)"}

**REPRODUCTION STEPS:**
{reproduction_steps or "(empty)"}

**ENVIRONMENT:** {environment or "(empty)"}

**EXPECTED BEHAVIOR:** {expected_behavior or "(empty)"}

**ACTUAL BEHAVIOR:** {actual_behavior or "(empty)"}

**SCREENSHOTS PROVIDED:** {len(screenshot_urls)} image(s)

Analyze the screenshots and text. Return a structured validation result with:
1. Individual scores (clarity, completeness, actionability, screenshot quality, reproducibility)
2. Overall score and severity
3. Specific missing information
4. Actionable suggestions for improvement
5. Assessment of each screenshot
6. Detected issue type and confidence"""

        # Build messages with vision content
        messages = [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": user_prompt
                    }
                ] + [
                    {
                        "type": "image_url",
                        "image_url": {"url": url, "detail": "high"}
                    }
                    for url in screenshot_urls if url.strip()
                ]
            }
        ]

        try:
            # Use GPT-4 Turbo with vision
            vision_model = os.getenv('OPENAI_VISION_MODEL', 'gpt-4-turbo')
            timeout = int(os.getenv('OPENAI_VALIDATION_TIMEOUT', '15'))

            logger.info(f"Calling OpenAI vision model: {vision_model}")

            # Use function calling for structured output
            response = self.client.chat.completions.create(
                model=vision_model,
                messages=messages,
                temperature=0.2,  # Lower for consistency
                max_tokens=int(os.getenv('OPENAI_VISION_MAX_TOKENS', '1500')),
                tools=[{
                    "type": "function",
                    "function": {
                        "name": "validate_issue",
                        "description": "Validate a GitHub issue and return structured feedback",
                        "parameters": IssueValidationResult.model_json_schema()
                    }
                }],
                tool_choice={"type": "function", "function": {"name": "validate_issue"}}
            )

            # Extract function call result
            tool_call = response.choices[0].message.tool_calls[0]
            result_json = tool_call.function.arguments
            result = IssueValidationResult.model_validate_json(result_json)

            logger.info(f"Validation complete. Score: {result.score}/100, Severity: {result.severity}")

            return result

        except Exception as e:
            logger.error(f"Validation error: {e}", exc_info=True)
            # Return a minimal valid result on error
            return IssueValidationResult(
                score=50,
                is_actionable=True,
                severity="needs_improvement",
                clarity_score=5,
                completeness_score=5,
                actionability_score=5,
                screenshot_score=5,
                reproducibility_score=5,
                missing_info=[f"Validation failed: {str(e)}"],
                suggestions=["Please try creating the issue again"],
                detected_type="bug",
                confidence=0.5
            )

# Initialize the bot
llm_bot = LLMBot()
