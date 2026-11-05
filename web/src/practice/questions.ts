/** Match the server's explicit-selection contract without coupling to a Router. */
export function questionsForApplication<T extends { application_id: string | null }>(
  questions: readonly T[], applicationId?: string | null,
): T[] {
  return questions.filter(question => !applicationId || !question.application_id || question.application_id === applicationId);
}
