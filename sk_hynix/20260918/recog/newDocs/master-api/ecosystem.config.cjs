module.exports = {
  apps: [{
    name: 'master-api',
    script: './app.js',
    instances: 1,
    exec_mode: 'fork',
    autorestart: true,
    watch: false,
    max_memory_restart: '3G',
    env: {
      NODE_ENV: 'production'
    }
  }]
};
