import { axiosClient, axiosClientFile, axiosPublicClient } from './axiosClient';
import { buildApiUrl } from './apiBase';

/**
 * Đăng nhập.
 * POST /api/v1/auth/login
 * @param {string} email
 * @param {string} password
 * @returns {object} account info
 */
export async function login(email, password) {
    const res = await axiosClient.post('/api/v1/auth/login', { email, password });
    return res.data;
}

/**
 * Đăng xuất — xóa cookie.
 * POST /api/v1/auth/logout
 */
export async function logout() {
    const res = await axiosClient.post('/api/v1/auth/logout');
    return res.data;
}

/**
 * Lấy thông tin user hiện tại (kiểm tra phiên).
 * GET /api/v1/auth/me
 * @returns {object} { status, result: { id, email, name, roles, ... } }
 */
export async function getMe() {
    const res = await axiosClient.get('/api/v1/auth/me');
    return res.data;
}

/**
 * Đăng ký tài khoản mới.
 * POST /api/v1/auth/register
 * @param {string} email
 * @param {string} password
 * @param {string} name
 * @returns {object} account info
 */
export async function register(email, password, name) {
    const res = await axiosClient.post('/api/v1/auth/register', { email, password, name });
    return res.data;
}

/**
 * Quên mật khẩu — gửi mật khẩu mới qua email.
 * POST /api/v1/auth/forgot-password
 * @param {string} email
 */
export async function forgotPassword(email) {
    const res = await axiosClient.post('/api/v1/auth/forgot-password', { email });
    return res.data;
}

/**
 * Xác thực email bằng one-time token (public endpoint).
 * POST /api/v1/auth/verify-email/confirm
 * @param {string} verificationToken
 */
export async function verifyEmailToken(verificationToken) {
    const res = await axiosPublicClient.post('/api/v1/auth/verify-email/confirm', {
        verification_token: verificationToken,
    });
    return res.data;
}

/**
 * Cập nhật profile.
 * PUT /api/v1/auth/profile
 * @param {object} data - { name?, phone?, address?, password? }
 */
export async function updateProfile(data) {
    const res = await axiosClient.put('/api/v1/auth/profile', data);
    return res.data;
}

/**
 * Upload avatar.
 * PUT /api/v1/auth/profile/avatar
 * @param {File} file
 */
export async function uploadAvatar(file) {
    const formData = new FormData();
    formData.append('file', file);
    const res = await axiosClientFile.put('/api/v1/auth/profile/avatar', formData);
    return res.data;
}

/**
 * Lấy URL avatar cho account.
 * @param {number} accountId
 * @returns {string} URL
 */
export function getAvatarUrl(accountId) {
    return buildApiUrl(`/api/v1/auth/avatar/${accountId}`);
}

/**
 * [Admin] Lấy danh sách tất cả accounts.
 * GET /api/v1/auth/accounts
 */
export async function getAccounts() {
    const res = await axiosClient.get('/api/v1/auth/accounts');
    return res.data;
}

/**
 * [Admin] Cập nhật roles cho account.
 * PUT /api/v1/auth/accounts/{id}/roles
 */
export async function updateRoles(accountId, roles) {
    const res = await axiosClient.put(`/api/v1/auth/accounts/${accountId}/roles`, { account_id: accountId, roles });
    return res.data;
}

/**
 * [Admin] Kích hoạt account.
 * PUT /api/v1/auth/accounts/{id}/activate
 */
export async function activateAccount(accountId) {
    const res = await axiosClient.put(`/api/v1/auth/accounts/${accountId}/activate`);
    return res.data;
}

/**
 * [Admin] Vô hiệu hóa account.
 * PUT /api/v1/auth/accounts/{id}/deactivate
 */
export async function deactivateAccount(accountId) {
    const res = await axiosClient.put(`/api/v1/auth/accounts/${accountId}/deactivate`);
    return res.data;
}

/**
 * [Admin] Xóa account.
 * DELETE /api/v1/auth/accounts/{id}
 */
export async function deleteAccount(accountId) {
    const res = await axiosClient.delete(`/api/v1/auth/accounts/${accountId}`);
    return res.data;
}

/**
 * Gửi heartbeat ping để giữ trạng thái online.
 * POST /api/v1/auth/heartbeat/ping
 */
export async function heartbeatPing() {
    const res = await axiosClient.post('/api/v1/auth/heartbeat/ping');
    return res.data;
}

/**
 * [Admin] Kiểm tra trạng thái online của danh sách users.
 * POST /api/v1/auth/heartbeat/check
 * @param {number[]} userIds
 */
export async function heartbeatCheck(userIds) {
    const res = await axiosClient.post('/api/v1/auth/heartbeat/check', { user_ids: userIds });
    return res.data;
}

/**
 * [Admin] Lấy danh sách thông báo bảo mật.
 * GET /api/v1/auth/notifications
 */
export async function getNotifications(limit = 50, offset = 0) {
    const res = await axiosClient.get('/api/v1/auth/notifications', {
        params: { limit, offset }
    });
    return res.data;
}

/**
 * [Admin] Lấy danh sách thông báo bảo mật đã đọc.
 * PUT /api/v1/auth/notifications/{id}/read
 */
export async function markNotificationRead(notificationId) {
    const res = await axiosClient.put(`/api/v1/auth/notifications/${notificationId}/read`);
    return res.data;
}

/**
 * [Admin] Lấy lịch sử đăng nhập.
 * GET /api/v1/auth/login-history
 * @param {number|null} accountId
 * @param {number} limit
 * @param {number} offset
 */
export async function getLoginHistory(accountId = null, limit = 20, offset = 0) {
    const res = await axiosClient.get('/api/v1/auth/login-history', {
        params: { account_id: accountId, limit, offset }
    });
    return res.data;
}

/**
 * [Admin] Xóa một thông báo bảo mật.
 * DELETE /api/v1/auth/notifications/{id}
 */
export async function deleteNotification(notificationId) {
    const res = await axiosClient.delete(`/api/v1/auth/notifications/${notificationId}`);
    return res.data;
}

/**
 * [Admin] Xóa tất cả thông báo đã đọc.
 * DELETE /api/v1/auth/notifications/all-read
 */
export async function deleteAllReadNotifications() {
    const res = await axiosClient.delete('/api/v1/auth/notifications/all-read');
    return res.data;
}

/**
 * [Admin] Xóa một bản ghi lịch sử đăng nhập theo ID.
 * DELETE /api/v1/auth/login-history/entry/{entryId}
 */
export async function deleteLoginHistoryEntry(entryId) {
    const res = await axiosClient.delete(`/api/v1/auth/login-history/entry/${entryId}`);
    return res.data;
}

/**
 * [Admin] Xóa toàn bộ lịch sử đăng nhập của một tài khoản.
 * DELETE /api/v1/auth/login-history/{accountId}
 */
export async function deleteLoginHistory(accountId) {
    const res = await axiosClient.delete(`/api/v1/auth/login-history/${accountId}`);
    return res.data;
}

/**
 * [Admin] Lấy danh sách tất cả roles hệ thống.
 * GET /api/v1/auth/roles
 */
export async function getRoles() {
    const res = await axiosClient.get('/api/v1/auth/roles');
    return res.data;
}

/**
 * [Admin] Tạo role mới.
 * POST /api/v1/auth/roles
 * @param {string} name
 * @param {string} description
 */
export async function createRole(name, description) {
    const res = await axiosClient.post('/api/v1/auth/roles', { name, description });
    return res.data;
}

/**
 * [Admin] Cập nhật role.
 * PUT /api/v1/auth/roles/{id}
 */
export async function updateRole(roleId, name, description) {
    const res = await axiosClient.put(`/api/v1/auth/roles/${roleId}`, { name, description });
    return res.data;
}

/**
 * [Admin] Xóa role.
 * DELETE /api/v1/auth/roles/{id}
 */
export async function deleteRole(roleId) {
    const res = await axiosClient.delete(`/api/v1/auth/roles/${roleId}`);
    return res.data;
}


// =============================================================================
// Analytics Management
// =============================================================================

export async function getAdminAnalytics() {
    const res = await axiosClient.get('/api/v1/analytics/admin');
    return res.data;
}

export async function getUserAnalytics() {
    const res = await axiosClient.get('/api/v1/analytics/me');
    return res.data;
}

export async function getSystemMetrics() {
    const res = await axiosClient.get('/api/v1/analytics/system-metrics');
    return res.data;
}
