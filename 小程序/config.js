// The sandbox AppID cannot complete CloudBase environment binding (IDE error
// -601059), so the current preview uses the server test bridge. Formal AppIDs
// must switch this value to 'cloud'.
module.exports = {
  mode: 'test-http',
  envId: 'wxapp-backend-test-d5c9k701c7cf2',
  gateway: 'nameGateway',
  coreBaseUrl: 'https://name.sensen.li'
};
