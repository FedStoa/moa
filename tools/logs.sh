#!/usr/bin/env bash

# Made with "Get you a multitail"
# https://getyouamultitail.link/?d=N4IgbiBcCMA0IBsoG1QIIYCMCmTImhHgGMB7BUgJyhEuwBMiQAzASwWxoHox1KuA7kK4BbUui4UA5gGdBVANbZKAfWgA6aUzIiRdZjQAMIAL6w0WXDQBM28lRpS62AHZM2Hbr35CBo8ZKksvKUSqrWmkF2uvpGpuaIlnggAMx2FNT4AJ64FALu7Jz4PHyCwmIS0nICisoqKZFS0XrYBvjGZhY4yQAs6Q74mAgArpzwHkUgJT7lAVUhYSo9jc2x7fFdVvgArP2ZICLoUq4ALugFnsXeZX4VgcE1oXXbKySkMa1xJgC68PTYMmINAAsuIAASPMJgqpMMAACygzHQCBk2HgIi+QA

# Moa worker logs

multitail -m 0 --label '[1] ' -ci red -I /var/www/moa/logs/worker_1.log --label '[2] ' -ci green -I /var/www/moa/logs/worker_2.log --label '[3] ' -ci yellow -I /var/www/moa/logs/worker_3.log --label '[4] ' -ci blue -I /var/www/moa/logs/worker_4.log --label '[5] ' -ci magenta -I /var/www/moa/logs/worker_5.log 
