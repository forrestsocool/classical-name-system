// Test AppID cannot use CloudBase (WeChat returns -601059), so local preview uses
// the server's short-lived wx.login bridge. Formal mini-programs switch to cloud.
module.exports = {
  mode: 'test-http',
  envId: 'wxapp-backend-test-d5c9k701c7cf2',
  gateway: 'nameGateway',
  coreBaseUrl: 'https://name.sensen.li'
};
