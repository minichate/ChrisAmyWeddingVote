from google.appengine.ext import webapp
from google.appengine.api import channel
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.api import memcache
from tropo import Tropo
import simplejson
from datetime import datetime
import os

from google.appengine.ext import db
import random

class SimpleCounterShard(db.Model):
    """Shards for the counter"""
    count = db.IntegerProperty(required=True, default=0)
    
class ChannelIdentifier(db.Model):
    channel_id = db.StringProperty(required=True)
    stamp = db.DateTimeProperty(required=True)

NUM_SHARDS = 20

def get_count():
    """Retrieve the value for a given sharded counter."""
    total = memcache.get('votes')
    if total is not None:
        return total
    
    total = 0
    for counter in SimpleCounterShard.all():
        total += counter.count
        
    memcache.set('votes', total)
    return total

def increment():
    """Increment the value for a given sharded counter."""
    def txn():
        index = random.randint(0, NUM_SHARDS - 1)
        shard_name = "shard" + str(index)
        counter = SimpleCounterShard.get_by_key_name(shard_name)
        if counter is None:
            counter = SimpleCounterShard(key_name=shard_name)
        counter.count += 1
        counter.put()
        
        memcache.delete('votes')
        
    db.run_in_transaction(txn)


def get_registered_channels():
    channels = simplejson.loads(memcache.get('channels') or '{}')
    if len(channels) is 0:
        for channel in ChannelIdentifier.all():
            channels[channel.channel_id] = str(channel.stamp)
        
    return channels
    

class MainPage(webapp.RequestHandler):
    def get(self):
        channel_id = os.urandom(16).encode('hex')
        
        token = channel.create_channel(channel_id)
        
        channels = get_registered_channels()
        
        channels[channel_id] = str(datetime.now())
        memcache.set('channels', simplejson.dumps(channels))
        
        template_values = {'token': token, 'count': str(get_count())}
        
        self.response.out.write(template.render('index.html', template_values))
        
class RecordPage(webapp.RequestHandler):
    def get(self):
        increment()
        
        channels = get_registered_channels()
        for channel_id in channels.iterkeys():
            channel.send_message(channel_id, str(get_count()))
    
    def post(self):
        self.get()
        
        t = Tropo()
        t.say(["Thanks! Your vote has been recorded"])
        self.response.out.write(t.RenderJson())
        
class ConnectedChannelPage(webapp.RequestHandler):
    def post(self):
        channel_id = self.request.get('from')
        channel_obj = ChannelIdentifier(channel_id=channel_id, stamp=datetime.now())
        channel_obj.put()
        
class DisconnectedChannelPage(webapp.RequestHandler):
    def post(self):
        channel_id = self.request.get('from')
        for channel in ChannelIdentifier.all():
            if channel.channel_id == channel_id:
                channel.delete()
                
class FlushCacheHandler(webapp.RequestHandler):
    def get(self):
        memcache.flush_all()

application = webapp.WSGIApplication(
                                     [('/', MainPage), 
                                      ('/record.*', RecordPage), 
                                      ('/_ah/channel/connected/', ConnectedChannelPage),
                                      ('/_ah/channel/disconnected/', DisconnectedChannelPage),
                                      ('/flush', FlushCacheHandler),
                                      ],
                                     debug=False)

def main():
    run_wsgi_app(application)

if __name__ == "__main__":
    main()