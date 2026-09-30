/* API errors, translated once.
 *
 * Ported from app/ui/state/api_client.py. The messages are copied verbatim rather
 * than rewritten: section 9 preserves product decisions, and these strings are the
 * ones users have been reading. An unrecognised code degrades to the generic
 * sentence — an English internal code in a Hebrew interface is worse than a vague
 * message the user can act on.
 *
 * Screens never format an error themselves; they render `error.message`.
 */

export const MESSAGES: Record<string, string> = {
  UNAUTHENTICATED: 'פג תוקף החיבור. יש להתחבר מחדש.',
  FORBIDDEN: 'אין לך הרשאה לפעולה הזו.',
  ADMIN_REQUIRED: 'האזור הזה מיועד למנהלי מערכת בלבד.',
  NOT_FOUND: 'לא מצאנו את מה שחיפשת.',
  PLANT_NOT_FOUND: 'הצמח לא נמצא.',
  VALIDATION_FAILED: 'חלק מהפרטים אינם תקינים. אנא בדקו ונסו שוב.',
  INVALID_TRANSITION: 'לא ניתן לבצע את השינוי הזה במצב הנוכחי.',
  IMAGE_INVALID: 'לא הצלחנו לקרוא את התמונה. נסו קובץ אחר.',
  PAYLOAD_TOO_LARGE: 'הקובץ גדול מדי. הגודל המרבי הוא 10MB.',
  DUPLICATE_ACTION: 'הפעולה כבר נרשמה.',
  RATE_LIMITED: 'ביצעת יותר מדי בקשות. נסו שוב בעוד רגע.',
  AGENT_FAILED: 'הניתוח לא הושלם. אפשר לנסות שוב.',
  AGENT_SCHEMA_INVALID: 'הניתוח לא הושלם. אפשר לנסות שוב.',
  AGENT_TIMEOUT: 'הניתוח נמשך זמן רב מדי. אפשר לנסות שוב.',
  UPSTREAM_UNAVAILABLE: 'שירות חיצוני אינו זמין כרגע.',
  CONFIGURATION_ERROR: 'יש תקלה בהגדרות המערכת.',
  // Added by a later backend change: the vendor refused and the model never ran,
  // which is a different thing to tell a user than "the analysis failed".
  AGENT_UNAVAILABLE: 'שירות ה-AI עמוס כרגע. אפשר לנסות שוב בעוד רגע.',
}

export const GENERIC = 'משהו השתבש. אפשר לנסות שוב.'
export const OFFLINE = 'לא הצלחנו להתחבר לשרת. בדקו את החיבור ונסו שוב.'

export class ApiError extends Error {
  readonly code: string
  readonly status?: number
  readonly details: Record<string, unknown>
  readonly requestId?: string

  constructor(
    code: string,
    message: string,
    opts: { status?: number; details?: Record<string, unknown>; requestId?: string } = {},
  ) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = opts.status
    this.details = opts.details ?? {}
    this.requestId = opts.requestId
  }

  get isAuthError(): boolean {
    return this.code === 'UNAUTHENTICATED' || this.status === 401
  }
}

/** Turn an API_CONTRACTS error envelope into a displayable error. */
export function translate(payload: unknown, status: number): ApiError {
  const body = (payload ?? {}) as { error?: Record<string, unknown>; request_id?: string }
  const error = body.error ?? {}
  const code = String(error.code ?? 'INTERNAL_ERROR')
  return new ApiError(code, MESSAGES[code] ?? GENERIC, {
    status,
    details: (error.details as Record<string, unknown>) ?? {},
    requestId: body.request_id,
  })
}
