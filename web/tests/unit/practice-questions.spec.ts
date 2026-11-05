import { expect, test } from '@playwright/test';
import { questionsForApplication } from '../../src/practice/questions';

const questions = [
  { id: 'own', application_id: 'application-a', source: 'generated' },
  { id: 'public', application_id: null, source: 'bank' },
  { id: 'other', application_id: 'application-b', source: 'generated' },
  { id: 'unlinked', application_id: null, source: 'custom' },
];

test('linked practice includes its own and unlinked questions in the original order', () => {
  expect(questionsForApplication(questions, 'application-a').map(q => q.id)).toEqual(['own', 'public', 'unlinked']);
  expect(questionsForApplication(questions, 'application-b').map(q => q.id)).toEqual(['public', 'other', 'unlinked']);
});

test('unlinked practice preserves all questions without changing the source list', () => {
  const before = structuredClone(questions);
  for (const application of [null, undefined, '']) {
    expect(questionsForApplication(questions, application)).toEqual(questions);
  }
  expect(questions).toEqual(before);
});

test('an empty question list remains empty for every application', () => {
  expect(questionsForApplication([], 'application-a')).toEqual([]);
});
