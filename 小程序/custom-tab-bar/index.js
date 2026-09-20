Component({
  data: {
    selected: 0,
    items: [
      {path: '/pages/discover/index', text: '千千嘉名', icon: '/assets/icons/tab-discover.svg', activeIcon: '/assets/icons/tab-discover-active.svg'},
      {path: '/pages/favorites/index', text: '我的收藏', icon: '/assets/icons/tab-heart.svg', activeIcon: '/assets/icons/tab-heart-active.svg'},
      {path: '/pages/profile/index', text: '个人中心', icon: '/assets/icons/tab-user.svg', activeIcon: '/assets/icons/tab-user-active.svg'}
    ]
  },
  methods: {
    switchTab(event) {
      const index = Number(event.currentTarget.dataset.index);
      const item = this.data.items[index];
      if (!item || index === this.data.selected) return;
      wx.switchTab({url: item.path});
    }
  }
});
