'use strict';
const cloud = require('wx-server-sdk');
const { createHandler } = require('./gateway');
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });
exports.main = createHandler({ getContext: () => cloud.getWXContext() });
