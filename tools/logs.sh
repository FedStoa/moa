#!/usr/bin/env bash

# Made with "Get you a multitail"
# https://getyouamultitail.link/?d=N4IgbiBcCMA0IBsoG1QIIYCMCmTImhHgGMB7BUgJyhEuwBMiQAzASwWxoHox1KuA7kK4BbUui4UA5gGdBVANbZKAfWgA6aUzIiRdZjQAMIAL6w0WXDUIlyVGlLrYAdkzYduvfkIGjxk0ll5SiVVACZNQO1SXX0jU3NESzwCaIpqfABPXAoBN3ZOfB4+QWExCWk5AUVlFQBmSKlo2OwDfGMzCxwUmxAydJpMBABXTnh3QpBi7zL-SuDQlQAWRua9VvjOpO7rNPt8EXQpFwAXdHyPIq9S33KAoOqQ2oBWVdsWtpAOgF14emwZMQaABZcQAAkeoTBlSYYAAFlBmOgEDJsPARJsgA

# Moa worker logs

multitail -m 0 --label '[1] ' -ci red -I /var/www/moa/logs/worker_1.log --label '[1] ' -ci green -I /var/www/moa/logs/worker_2.log --label '[1] ' -ci yellow -I /var/www/moa/logs/worker_3.log --label '[1] ' -ci blue -I /var/www/moa/logs/worker_4.log --label '[1] ' -ci magenta -I /var/www/moa/logs/worker_5.log
