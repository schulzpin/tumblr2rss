from flask import Flask, request, g, session, abort, redirect, make_response
from flask.templating import render_template
import oauth2
import sqlite3
import json
import urllib
import urlparse
import PyRSS2Gen as rss
import datetime
import cStringIO
from jinja2 import Template
import sys, os

PATH = os.getcwd()
##Production
SERVER_NAME = "http://tumblr2rss.joshkunz.com"

##Dev
#SERVER_NAME = "http://localhost:5000"

sys.path.append(PATH)
import config

app = Flask(__name__)
app.debug = True

app.secret_key = config.secret_key #Secret key for flask Sessions
CONSUMER_KEY = config.CONSUMER_KEY #Tumblr API Consumer Key
CONSUMER_SECRET = config.CONSUMER_SECRET #Tumblr API Consumer Secret


post_templates = {
	"text": """
	{{ body|safe }}
	""",
	
	"photo": """
	{%- for photo in photos -%}
		<img src="{{ photo.original_size.url }}" />
		{% if photo.caption %}<p>{{ photo.caption }}</p>{% endif %}
	{% endfor %}
	{% if caption %}<p>{{ caption }}</p>{% endif %}
	""",
	
	"quote": """
	<p>{{ text }}</p>
	{{ source|safe }}
	""",
	
	"link": """
	<a href="{{ url }}">
		{%- if title -%}
			{{ title }}
		{%- else -%}
			{{ url }}
		{% endif %}
	</a>
	{{ description|safe }}
	""",
	
	"chat": """
	{% for line in dialogue %}
		<p>{{ label }} {{ phrase }}</p>
	{% endfor %}
	""",
	
	"audio": """
	{{ player|safe }}
	{{ caption|safe }}
	""",
	
	"video": """
	{% set largest_player = player|sort(reverse=True, attribute='width')|first %}
	{{ largest_player.embed_code|safe }}
	{{ caption|safe }}
	"""
}

#Decorate the templates
for name, values in post_templates.iteritems():
	post_templates[name] = Template(post_templates[name])

@app.before_request
def setup():
	g.db = sqlite3.connect(PATH+"users.db")
	g.c = g.db.cursor()
	
	def setupdb():
		g.c.execute("""
				 CREATE TABLE IF NOT EXISTS user
				 (username text, oauth_key text, oauth_secret text)
				 """)
	setupdb()
	
@app.route("/")
def index():
	return render_template("index.html")

@app.route("/register", methods=["GET"])
def register():
	#Else it's a post
	
	consumer = oauth2.Consumer(CONSUMER_KEY, CONSUMER_SECRET)
	client = oauth2.Client(consumer)
	
	#According to spec one must be provided, however most
	#implementations could care less
	body = urllib.urlencode({"oauth_callback": SERVER_NAME+"/done"})
	
	resp, content = client.request("http://www.tumblr.com/oauth/request_token", "POST", body=body)
	if resp["status"] != "200": abort(400)
		
	session["request_token"] = dict(urlparse.parse_qsl(content))
	return redirect("http://www.tumblr.com/oauth/authorize?oauth_token={0}".format(session["request_token"]["oauth_token"]))
	
@app.route("/done")
def finish():
	"finish the auth process"
	
	print "Has Session"
	
	token = oauth2.Token(session["request_token"]["oauth_token"], session["request_token"]["oauth_token_secret"])
	token.set_verifier(request.args.get("oauth_verifier"))
	
	consumer = oauth2.Consumer(CONSUMER_KEY, CONSUMER_SECRET)
	client = oauth2.Client(consumer, token)
	
	#request the 
	resp, content = client.request("http://www.tumblr.com/oauth/access_token", "POST")
	if resp["status"] != "200": abort(400)
	
	d= dict(urlparse.parse_qsl(content))
	
	token = oauth2.Token(d["oauth_token"], d["oauth_token_secret"])
	client = oauth2.Client(consumer, token)
	
	resp, data = client.request("http://api.tumblr.com/v2/user/info", "POST")
	user_info_resp = json.loads(data)
	
	g.c.execute("""
				INSERT INTO user values (?, ?, ?)
				""", (user_info_resp["response"]["user"]["name"],
					  d["oauth_token"],
					  d["oauth_token_secret"]))
	g.db.commit()
	
	return render_template("registered.html", user=user_info_resp["response"]["user"]["name"])

def render_rss(response, username="Unknown"):
	items = []
	for item in response["posts"]:
		items.append(rss.RSSItem(
			title = item.get("title", "Tumblr: "+item["type"]),
			link = item["post_url"],
			description = post_templates[item["type"]].render(**item),
			pubDate = datetime.datetime.strptime(item["date"], "%Y-%m-%d %H:%M:%S GMT"),
			guid = rss.Guid(item["post_url"])
		))
	
	feed = rss.RSS2(
		title = "{0}'s Tumblr Dashboard".format(username),
		link = "http://{0}/{1}".format(SERVER_NAME, username),
		description = "Automaticaly generated feed of {0}'s dashboard.".format(username),
		lastBuildDate = datetime.datetime.utcnow(),
		items = items
	)
	
	filefeed = cStringIO.StringIO()
	feed.write_xml(filefeed)
	
	resp = make_response(filefeed.getvalue(), 200)
	
	filefeed.close()
	
	resp.headers["Content-Type"] = "application/rss+xml"
	return resp

@app.route("/feed/<path:username>.rss")
def user_posts(username):
	
	import urllib2, urllib
	args = urllib.urlencode({
		"api_key": CONSUMER_KEY
	})
	posts = urllib2.urlopen(
		"http://api.tumblr.com/v2/blog/{0}/posts?".format(username)+args).read()
	posts = json.loads(posts)
	return render_rss(posts["response"], username=username)
	
@app.route("/<username>.rss")
def user_dash(username):
	
	g.c.execute("""
				SELECT username, oauth_key, oauth_secret from user
				WHERE username = ? limit 1
				""", (username,))
	
	user = [x for x in g.c]
	
	if user: user = user[0]
	else: abort(404)
	
	consumer = oauth2.Consumer(CONSUMER_KEY, CONSUMER_SECRET)
	token = oauth2.Token(user[1], user[2])
	client = oauth2.Client(consumer, token)
	
	resp, user_dash = client.request("http://api.tumblr.com/v2/user/dashboard", "GET")
	
	user_dash = json.loads(user_dash)
	
	return render_rss(user_dash["response"], username=user[0])

if __name__ == '__main__':
	app.run()
elif __name__ != '__main__':
	application = app