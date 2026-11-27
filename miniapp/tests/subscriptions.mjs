import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import ts from 'typescript';

const events = [];
const globals = {
  URL, URLSearchParams,
  window: { dispatchEvent: event => events.push(event) },
  CustomEvent: class { constructor(type, config) { this.type = type; this.detail = config.detail; } },
};
const loaded = new Map();
function load(name) {
  if (!loaded.has(name)) {
    const context = { ...globals, exports: {}, require: path => load(path.replace(/^\.\//, '')) };
    loaded.set(name, context.exports);
    vm.runInNewContext(ts.transpileModule(readFileSync(new URL(`../src/lib/${name}.ts`, import.meta.url), 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.CommonJS },
    }).outputText, context);
    loaded.set(name, context.exports);
  }
  return loaded.get(name);
}
const api = load('subscriptions');
assert.deepEqual(Object.keys(api.paidSubjectTitles).sort(), ['anatomy', 'anatomy_tests', 'biology', 'chemistry', 'histology', 'physics']);
assert.equal(api.paidSubjectTitles.anatomy_tests, 'Тесты по анатомии');
assert.equal(api.paidSubjectTitles.histology, 'Гистология');
for (const value of ['https://bad.example', '//bad.example', '/profile/subscriptions', '/subjects/../profile']) {
  assert.equal(api.subscriptionReturnPath(value), '/profile');
}
assert.equal(api.subscriptionReturnPath('/histology/exam'), '/histology/exam');
const url = new URL(api.subscriptionPath('histology', '/histology/exam'), 'https://miniapp.test');
assert.equal(url.searchParams.get('subject'), 'histology');
assert.equal(url.searchParams.get('returnTo'), '/histology/exam');
const trialOffer = new URL(api.subscriptionPath('anatomy_tests', '/tests/anatomy', 32), 'https://miniapp.test');
assert.equal(trialOffer.searchParams.get('plan'), '32');
assert.equal(trialOffer.searchParams.get('returnTo'), '/tests/anatomy');
for (const [status, subject] of [[403, 'histology'], [403, null], [503, 'histology'], [403, 'unknown']]) {
  api.notifySubscriptionRequired({ status, headers: { get: () => subject } });
}
assert.equal(events.length, 1);
assert.equal(events[0].detail.subjectId, 'histology');
const options = [{id: 'biology'}, {id: 'chemistry'}];
assert.equal(api.planSubject(options, undefined, 'biology'), 'biology');
assert.equal(api.planSubject(options, 'chemistry', 'biology'), 'chemistry');
assert.equal(api.planSubject(options, undefined, 'anatomy'), undefined);
assert.equal(api.planSubject([], undefined, 'biology'), undefined);
assert.equal(api.planSubject([], 'chemistry', 'biology'), undefined);
const bundleSubject = api.planSubject([], undefined, 'histology');
assert.equal(JSON.stringify({tier_id: 24, subject: bundleSubject}), '{"tier_id":24}');
assert.equal(`sbp-request:24:${bundleSubject ?? 'all'}`, 'sbp-request:24:all');
assert.equal(api.normalizePaymentLink('https://codeepay.xyz/transfer/stored-token?bank=1'), 'https://payment.codeepay.xyz/transfer/stored-token?bank=1');
assert.equal(api.normalizePaymentLink('https://payment.codeepay.xyz/transfer/provider-token'), 'https://payment.codeepay.xyz/transfer/provider-token');
for (const value of ['http://codeepay.xyz/transfer/x', 'https://evil.example/transfer/x', 'https://codeepay.xyz/not-payment/x']) {
  assert.throws(() => api.normalizePaymentLink(value), /Некорректная ссылка оплаты/);
}
console.log('Subscription navigation and checkout: contextual subject, safe return path, paid-only redirects, bundle payload and stable nonce OK');
