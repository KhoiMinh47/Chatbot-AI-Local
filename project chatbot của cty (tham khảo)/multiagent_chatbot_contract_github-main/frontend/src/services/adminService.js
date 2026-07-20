import { axiosClient } from './axiosClient';

/**
 * --- MAIL SERVER CONFIG ---
 */
export async function getMailConfigs() {
  const res = await axiosClient.get('/api/v1/admin/settings/mail');
  return res.data;
}

export async function addMailConfig(data) {
  const res = await axiosClient.post('/api/v1/admin/settings/mail', data);
  return res.data;
}

export async function updateMailConfig(id, data) {
  const res = await axiosClient.put(`/api/v1/admin/settings/mail/${id}`, data);
  return res.data;
}

export async function deleteMailConfig(id) {
  const res = await axiosClient.delete(`/api/v1/admin/settings/mail/${id}`);
  return res.data;
}

/**
 * --- TELEGRAM CONFIG ---
 */
export async function getTelegramBots() {
  const res = await axiosClient.get('/api/v1/admin/settings/telegram/bots');
  return res.data;
}

export async function addTelegramBot(data) {
  const res = await axiosClient.post('/api/v1/admin/settings/telegram/bots', data);
  return res.data;
}

export async function updateTelegramBot(id, data) {
  const res = await axiosClient.put(`/api/v1/admin/settings/telegram/bots/${id}`, data);
  return res.data;
}

export async function deleteTelegramBot(id) {
  const res = await axiosClient.delete(`/api/v1/admin/settings/telegram/bots/${id}`);
  return res.data;
}

export async function getTelegramRecipients() {
  const res = await axiosClient.get('/api/v1/admin/settings/telegram/recipients');
  return res.data;
}

export async function addTelegramRecipient(data) {
  const res = await axiosClient.post('/api/v1/admin/settings/telegram/recipients', data);
  return res.data;
}

export async function updateTelegramRecipient(id, data) {
  const res = await axiosClient.put(`/api/v1/admin/settings/telegram/recipients/${id}`, data);
  return res.data;
}

export async function deleteTelegramRecipient(id) {
  const res = await axiosClient.delete(`/api/v1/admin/settings/telegram/recipients/${id}`);
  return res.data;
}

/**
 * --- PROMPT CONFIG ---
 */
export async function getPromptFeatures() {
  const res = await axiosClient.get('/api/v1/admin/settings/prompt-features');
  return res.data;
}

export async function getPrompts() {
  const res = await axiosClient.get('/api/v1/admin/settings/prompts');
  return res.data;
}

export async function addPrompt(data) {
  const res = await axiosClient.post('/api/v1/admin/settings/prompts', data);
  return res.data;
}

export async function updatePrompt(id, data) {
  const res = await axiosClient.put(`/api/v1/admin/settings/prompts/${id}`, data);
  return res.data;
}

export async function deletePrompt(id) {
  const res = await axiosClient.delete(`/api/v1/admin/settings/prompts/${id}`);
  return res.data;
}

/**
 * --- LLM PROVIDER CONFIG ---
 */
export async function getLLMProviders() {
  const res = await axiosClient.get('/api/v1/admin/settings/llm-providers');
  return res.data;
}

export async function addLLMProvider(data) {
  const res = await axiosClient.post('/api/v1/admin/settings/llm-providers', data);
  return res.data;
}

export async function updateLLMProvider(id, data) {
  const res = await axiosClient.put(`/api/v1/admin/settings/llm-providers/${id}`, data);
  return res.data;
}

export async function deleteLLMProvider(id) {
  const res = await axiosClient.delete(`/api/v1/admin/settings/llm-providers/${id}`);
  return res.data;
}

/**
 * --- WEB SOURCE RULES ---
 */
export async function getWebSourceRules() {
  const res = await axiosClient.get('/api/v1/admin/settings/web-sources');
  return res.data;
}

export async function addWebSourceRule(data) {
  const res = await axiosClient.post('/api/v1/admin/settings/web-sources', data);
  return res.data;
}

export async function updateWebSourceRule(id, data) {
  const res = await axiosClient.put(`/api/v1/admin/settings/web-sources/${id}`, data);
  return res.data;
}

export async function deleteWebSourceRule(id) {
  const res = await axiosClient.delete(`/api/v1/admin/settings/web-sources/${id}`);
  return res.data;
}
