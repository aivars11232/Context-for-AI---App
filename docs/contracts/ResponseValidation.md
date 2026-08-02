# Response Validation and Correction Contract

## ResponseValidator
Input: context packet and candidate response. Output: pass/fail, score, typed violations, evidence.

Required checks: topic, intent, required constraints, forbidden actions, preservation rules, output type, completeness, repetition.

## CorrectionController
Input: failed response, validation report, current attempt count. Output: revision request or controlled exhaustion result.

Maximum revision attempts: 2.

## Never does
Silently weaken constraints, mutate the original user message, or continue beyond the configured limit.
