#!/usr/bin/env python
# IRCCEX Bot
# Developed by acidvegas in Python
# https://git.supernets.org/acidvegas/irccex
# irccex.py

import http.client
import json
import os
import pickle
import random
import socket
import time
import threading

######################### CONFIGURATION #########################
# Connection
server     = 'irc.server.com'
port	   = 6667
proxy      = None # Proxy should be a Socks5 in IP:PORT format.
use_ipv6   = False
use_ssl    = False
ssl_verify = False
vhost      = None
channel    = '#coin'
key        = None

# Certificate
cert_key  = None
cert_file = None
cert_pass = None

# Identity
nickname = 'IRCCEX'
username = 'irccex'
realname = 'https://git.supernets.org/acidvegas'

# Login
nickserv_password = None
network_password  = None
operator_password = None

# Settings
api_timeout      = 15
currency_convert = None # Defaults to USD
throttle_cmd     = 3    # Delay between command usage
throttle_msg     = 0.5  # Delay between messages sent
user_modes       = None

# Referral Links
referrals = {
	'binance'   : 'https://www.binance.com/?ref=CHANGEME',
	'coinbase'  : 'https://www.coinbase.com/join/CHANGEME',
	'hitbtc'    : 'https://hitbtc.com/?ref_id=CHANGEME',
	'kucoin'    : 'https://www.kucoin.com/#/?r=CHANGEME',
	'robinhood' : 'https://share.robinhood.com/CHANGEME'
}

# Limits & Fees
init_funds    = 1000.00 # USD amount given to start off
limit_cashout = 1500.00 # Minimum USD amount for !cashout
limit_send    = 1200.00 # Minimum USD amount for !send
limit_trade   = 5.00    # Minimum USD amount for !trade
fee_cashout   = 0.05    # % fee for !cashout (Default 5%)
fee_send      = 0.03    # % fee for !send    (Default 3%)
fee_trade     = 0.02    # % fee for !trade   (Default 2%)
max_assets    = 10      # Maximum number of different assets
################## DO NOT EDIT BELOW THIS LINE ##################

# Formatting Control Characters / Color Codes
bold        = '\x02'
italic      = '\x1D'
underline   = '\x1F'
reverse     = '\x16'
reset       = '\x0f'
white       = '00'
black       = '01'
blue        = '02'
green       = '03'
red         = '04'
brown       = '05'
purple      = '06'
orange      = '07'
yellow      = '08'
light_green = '09'
cyan        = '10'
light_cyan  = '11'
light_blue  = '12'
pink        = '13'
grey        = '14'
light_grey  = '15'

def condense_value(value):
	value = float(value)
	if value < 0.01:
		return '${0:,.8f}'.format(value)
	elif value < 24.99:
		return '${0:,.2f}'.format(value)
	else:
		return '${:,}'.format(int(value))

def condense_float(value):
	return '{0:.8g}'.format(float(value))

def debug(msg):
	print(f'{get_time()} | [~] - {msg}')

def error(msg, reason=None):
	if reason:
		print(f'{get_time()} | [!] - {msg} ({reason})')
	else:
		print(f'{get_time()} | [!] - {msg}')

def error_exit(msg):
	raise SystemExit(f'{get_time()} | [!] - {msg}')

def get_float(data):
	try:
		float(data)
		return True
	except ValueError:
		return False

def get_time():
	return time.strftime('%I:%M:%S')

def percent_color(percent):
	if float(percent) == 0.0:
		return grey
	elif percent.startswith('-'):
		if float(percent) > -10.0:
			return brown
		else:
			return red
	else:
		if float(percent) < 10.0:
			return green
		else:
			return light_green

def random_int(min, max):
    return random.randint(min, max)

class CoinMarketCap(object):
	def __init__(self):
		self.cache = None
		self.last  = 0

	def get(self):
		if self.cache:
			if time.time() - self.last < 300:
				return self.cache
			else:
				return self.api()
		else:
			return self.api()

	def api(self):
		conn = http.client.HTTPSConnection('api.coinmarketcap.com', timeout=api_timeout)
		if currency_convert:
			conn.request('GET', f'/v1/ticker/?convert={currency_convert}&limit=0')
		else:
			conn.request('GET', '/v1/ticker/?limit=0')
		response = conn.getresponse().read().replace(b'null', b'"0"')
		data = json.loads(response)
		conn.close()
		self.last  = int(data[0]['last_updated'])
		self.cache = data
		return data

class IRC(object):
	def __init__(self):
		self.bank        = dict()
		self.db          = dict()
		self.last        = 0
		self.maintenance = False
		self.slow        = False
		self.sock        = None
		self.verifying   = dict()

	def run(self):
		if os.path.isfile('bank.pkl'):
			with open('bank.pkl', 'rb') as bank_file:
				self.bank = pickle.load(bank_file)
		if os.path.isfile('db.pkl'):
			with open('db.pkl', 'rb') as db_file:
				self.bank = pickle.load(db_file)
		threading.Thread(target=self.loop_backup).start()
		threading.Thread(target=self.loop_maintenance).start()
		threading.Thread(target=self.loop_verify).start()
		self.connect()

	def cleanup(self, nick):
		for symbol in [asset for asset in self.db[nick] if not self.db[nick][asset]]:
			del self.db[nick][symbol]
		if not self.db[nick]:
			del self.db[nick]

	def coin_info(self, data, table=False):
		if table:
			name  = data['symbol']
			value = condense_value(data['price_usd'])
			percent = {'1h':data['percent_change_1h'],'24h':data['percent_change_24h'],'7d':data['percent_change_7d']}
			for item in percent:
				percent[item] = self.color('{0:,.2f}%'.format(float(percent[item])), percent_color(percent[item]))
			volume = '${:,}'.format(int(data['24h_volume_usd'].split('.')[0]))
			cap    = '${:,}'.format(int(data['market_cap_usd'].split('.')[0]))
			return ' {0} | {1} | {2}   {3}   {4} | {5} | {6} '.format(name.ljust(8),value.rjust(11),percent['1h'].rjust(14),percent['24h'].rjust(14),percent['7d'].rjust(14),volume.rjust(15),cap.rjust(16))
		else:
			sep     = self.color('|', grey)
			sep2    = self.color('/', grey)
			rank    = self.color(data['rank'], pink)
			name    = '{0} ({1})'.format(self.color(data['name'], white), data['symbol'])
			value   = condense_value(data['price_usd'])
			percent = {'1h':data['percent_change_1h'],'24h':data['percent_change_24h'],'7d':data['percent_change_7d']}
			for item in percent:
				percent[item] = self.color('{0:,.2f}%'.format(float(percent[item])), percent_color(percent[item]))
			perc   = '{0}{1}{2}{3}{4}'.format(percent['1h'], sep2, percent['24h'], sep2, percent['7d'])
			volume = '{0} {1}'.format(self.color('Volume:', white), '${:,}'.format(int(data['24h_volume_usd'].split('.')[0])))
			cap    = '{0} {1}'.format(self.color('Market Cap:', white), '${:,}'.format(int(data['market_cap_usd'].split('.')[0])))
			return f'[{rank}] {name} {sep} {value} ({perc}) {sep} {volume} {sep} {cap}'

	def color(self, msg, foreground, background=None):
		if background:
			return f'\x03{foreground},{background}{msg}{reset}'
		else:
			return f'\x03{foreground}{msg}{reset}'

	def connect(self):
		try:
			self.create_socket()
			self.sock.connect((server, port))
			self.register()
		except socket.error as ex:
			error('Failed to connect to IRC server.', ex)
			self.event_disconnect()
		else:
			self.listen()

	def create_socket(self):
		family = socket.AF_INET6 if use_ipv6 else socket.AF_INET
		if proxy:
			proxy_server, proxy_port = proxy.split(':')
			self.sock = socks.socksocket(family, socket.SOCK_STREAM)
			self.sock.setblocking(0)
			self.sock.settimeout(15)
			self.sock.setproxy(socks.PROXY_TYPE_SOCKS5, proxy_server, int(proxy_port))
		else:
			self.sock = socket.socket(family, socket.SOCK_STREAM)
		if vhost:
			self.sock.bind((vhost, 0))
		if use_ssl:
			ctx = ssl.SSLContext()
			if cert_file:
				ctx.load_cert_chain(cert_file, cert_key, cert_pass)
			if ssl_verify:
				ctx.verify_mode = ssl.CERT_REQUIRED
				ctx.load_default_certs()
			else:
				ctx.check_hostname = False
				ctx.verify_mode = ssl.CERT_NONE
			self.sock = ctx.wrap_socket(self.sock)

	def error(self, chan, msg, reason=None):
		if reason:
			self.sendmsg(chan, '[{0}] {1} {2}'.format(self.color('!', red), msg, self.color('({0})'.format(reason), grey)))
		else:
			self.sendmsg(chan, '[{0}] {1}'.format(self.color('!', red), msg))

	def event_connect(self):
		if user_modes:
			self.mode(nickname, '+' + user_modes)
		if nickserv_password:
			self.identify(nickname, nickserv_password)
		if operator_password:
			self.oper(username, operator_password)
		self.join_channel(channel, key)

	def event_disconnect(self):
		self.sock.close()
		time.sleep(10)
		self.connect()

	def event_kick(self, nick, chan, kicked):
		if kicked == nickname:
			time.sleep(3)
			self.join_channel(chan, key)

	def event_message(self, nick, chan, msg):
		try:
			nick = nick.lower()
			if msg[:1] in '!@$':
				if time.time() - self.last < throttle_cmd:
					if not self.slow:
						self.error(chan, 'Slow down nerd!')
						self.slow = True
				else:
					self.slow = False
					args = msg.split()
					if len(args) == 1:
						if msg == '@irccex':
							self.sendmsg(chan, bold + 'IRCCEX Bot - Developed by acidvegas in Python - https://git.supernets.org/acidvegas/irccex')
						elif msg == '@ref':
							for link in referrals:
								self.sendmsg(chan, '{0} {1}'.format(self.color(link + ':', white), self.color(referrals[link], light_blue)))
						elif msg.startswith('$'):
							if ',' in msg:
								coin_list  = list(dict.fromkeys(msg[1:].split(',')))[:10]
								data_lines = list()
								for coin in coin_list:
									api = [item for item in CMC.get() if (coin.lower() == item['id'] or coin.upper() == item['symbol'])]
									if api:
										data_lines.append(self.coin_info(api[0], True))
								if data_lines:
									if len(data_lines) == 1:
										coin = data_lines[0].split()[0]
										api = [item for item in CMC.get() if coin == item['symbol']]
										self.sendmsg(chan, self.coin_info(api[0]))
									else:
										self.sendmsg(chan, self.color('  Symbol       Value           1H          24H           7D         24H Volume        Market Cap    ', black, light_grey))
										for line in data_lines:
											self.sendmsg(chan, line)
								else:
									self.error(chan, 'Invalid cryptocurrency names!')
							else:
								coin = msg[1:]
								if not coin.isdigit():
									api  = [item for item in CMC.get() if (coin.lower() == item['id'] or coin.upper() == item['symbol'])]
									if api:
										self.sendmsg(chan, self.coin_info(api[0]))
									else:
										self.error(chan, 'Invalid cryptocurrency name!', coin)
						elif msg == '!bank':
							if nick in self.bank:
								self.sendmsg(chan, self.color('${:,}'.format(self.bank[nick]), green))
							else:
								self.error(chan, 'You don\'t have any money in the bank!')
						elif msg == '!bottom':
							data = CMC.get()[-10:]
							self.sendmsg(chan, self.color('  Symbol       Value           1H          24H           7D         24H Volume        Market Cap    ', black, light_grey))
							for item in data:
								self.sendmsg(chan, self.coin_info(item, True))
						elif msg == '!cashout':
							if nick in self.db:
								if 'USD' in self.db[nick]:
									if self.db[nick]['USD'] >= limit_cashout:
										amount = self.db[nick]['USD']-(self.db[nick]['USD']*fee_cashout)
										if nick not in self.bank:
											self.bank[nick] = amount
										else:
											self.bank[nick] += amount
										del self.db[nick]['USD']
										self.sendmsg(chan, 'You just cashed out {0} to your bank account, which is now at {1}'.format(self.color('$' + amount, light_blue), self.color('$' + self.bank[nick], light_blue)))
									else:
										self.error(chan, 'Insufficent funds.', f'${limit_cashout} minimum')
								else:
									self.error(chan, 'You have no USD in your account!')
							elif nick in self.verify:
								self.error(chan, 'Your account is not verified!')
							else:
								self.error(chan, 'You don\'t have an account!')
						elif msg == '!register':
							if not self.maintenance:
								if nick not in self.db and nick not in self.verifying:
									self.sendmsg(chan, 'Welcome to the IRC Cryptocurrency Exchange! Please wait 24 hours while we verify your documents!')
									self.verifying[nick] = time.time()
								else:
									self.error(chan, 'You already have an account!')
							else:
								self.error(chan, 'Exchange is down for scheduled maintenance. Please try again later.')
						elif msg == '!rich':
							if self.bank:
								richest = sorted(self.bank, key=self.bank.get, reverse=True)[:10]
								count = 1
								for user in richest:
									self.sendmsg(chan, '[{0}] {1} {2}'.format(self.color(count, pink), user, self.color('(${:,})'.format(self.bank[user]), grey)))
									count += 1
									time.sleep(throttle_msg)
							else:
								self.error(chan, 'Yall broke...')
						elif msg == '!top':
							data = CMC.get()[:10]
							self.sendmsg(chan, self.color('  Symbol       Value           1H          24H           7D         24H Volume        Market Cap    ', black, light_grey))
							for item in data:
								self.sendmsg(chan, self.coin_info(item, True))
								time.sleep(throttle_msg)
						elif msg == '!wallet':
							if not self.maintenance:
								if nick in self.db:
									self.sendmsg(chan, self.color('  Symbol          Amount                  Value        ', black, light_grey))
									total = 0
									for symbol in self.db[nick]:
										amount = self.db[nick][symbol]
										if symbol == 'USD':
											value = amount
										else:
											value = float([item for item in CMC.get() if symbol == item['symbol']][0]['price_usd'])*amount
										self.sendmsg(chan, ' {0} | {1} | {2} '.format(symbol.ljust(8), condense_float(amount).rjust(20), condense_value(value).rjust(20)))
										total += float(value)
										time.sleep(throttle_msg)
									self.sendmsg(chan, self.color('                            ' + ('Total: ' + condense_value(total)).rjust(27), black, light_grey))
								elif nick in self.verifying:
									self.sendmsg(chan, 'Your account is not verified yet!')
								else:
									self.error(chan, 'You don\'t have an account!')
							else:
								self.error(chan, 'Exchange is down for scheduled maintenance. Please try again later.')
					elif len(args) == 2:
						if msg == '@irccex help':
							self.sendmsg(chan, bold + 'https://git.supernets.org/acidvegas/irccex#commands')
						elif args[0] == '@ref':
							name = args[1]
							if name in referrals:
								self.sendmsg(chan, referrals[name])
							else:
								self.error(chan, 'Invalid referral name!', name)
						elif args[0] == '!bottom':
							options = {'1h':'percent_change_1h','24h':'percent_change_24h','7d':'percent_change_7d','value':'price_usd','volume':'24h_volume_usd'}
							try:
								option = options[args[1].lower()]
							except KeyError:
								self.error(chan, 'Invalid option!', 'Valid options are 1h, 24h, 7d, value, & volume')
							else:
								data        = CMC.get()
								sorted_data = {}
								for item in data:
									sorted_data[item['symbol']] = float(item[option])
								top_data = sorted(sorted_data, key=sorted_data.get, reverse=True)[-10:]
								self.sendmsg(chan, self.color('  Symbol       Value           1H          24H           7D         24H Volume        Market Cap    ', black, light_grey))
								for coin in top_data:
									api = [item for item in CMC.get() if coin == item['symbol']]
									self.sendmsg(chan, self.coin_info(api[0], True))
						elif args[0] == '!top':
							options = {'1h':'percent_change_1h','24h':'percent_change_24h','7d':'percent_change_7d','value':'price_usd','volume':'24h_volume_usd'}
							try:
								option = options[args[1].lower()]
							except KeyError:
								self.error(chan, 'Invalid option!', 'Valid options are 1h, 24h, 7d, value, & volume')
							else:
								data        = CMC.get()
								sorted_data = {}
								for item in data:
									sorted_data[item['symbol']] = float(item[option])
								top_data = sorted(sorted_data, key=sorted_data.get, reverse=True)[:10]
								self.sendmsg(chan, self.color('  Symbol       Value           1H          24H           7D         24H Volume        Market Cap    ', black, light_grey))
								for coin in top_data:
									api = [item for item in CMC.get() if coin == item['symbol']]
									self.sendmsg(chan, self.coin_info(api[0], True))
					elif len(args) == 3:
						if args[0] == '!trade':
							if not self.maintenance:
								if nick in self.db:
									pair = args[1].upper()
									if len(pair.split('/')) == 2:
										from_symbol, to_symbol = pair.split('/')
										if from_symbol in self.db[nick]:
											amount = args[2]
											if get_float(amount) or (amount.startswith('$') and get_float(amount[1:])):
												if amount.startswith('$'):
													if from_symbol != 'USD':
														value = float([item for item in CMC.get() if from_symbol == item['symbol']][0]['price_usd'])
														amount = float(amount[1:])/value
													else:
														amount = float(amount[1:])
												else:
													amount = float(amount)
												if self.db[nick][from_symbol] >= amount and amount > 0.0:
													fee_amount = amount-(amount*fee_trade)
													if from_symbol == 'USD':
														if to_symbol in ('BTC','ETH','LTC'):
															value = float([item for item in CMC.get() if to_symbol == item['symbol']][0]['price_usd'])
															recv_amount = fee_amount/value
															if to_symbol in self.db[nick]:
																self.db[nick]['USD'] -= amount
																self.db[nick][to_symbol] += recv_amount
																self.cleanup(nick)
																self.sendmsg(chan, 'Trade successful!')
															else:
																if len(self.db[nick]) < max_assets:
																	self.db[nick]['USD'] -= amount
																	self.db[nick][to_symbol] = recv_amount
																	self.cleanup(nick)
																	self.sendmsg(chan, 'Trade successful!')
																else:
																	self.error(chan, f'You can\'t hold more than {max_assets} assets!')
														else:
															self.error(chan, 'Invalid trade pair!', 'Can only trade USD for BTC, ETH, & LTC.')
													elif to_symbol == 'USD':
														if from_symbol in ('BTC','ETH','LTC'):
															value = float([item for item in CMC.get() if from_symbol == item['symbol']][0]['price_usd'])
															recv_amount = fee_amount*value
															if to_symbol in self.db[nick]:
																self.db[nick][from_symbol] -= amount
																self.db[nick][to_symbol] += recv_amount
																self.cleanup(nick)
																self.sendmsg(chan, 'Trade successful!')
															else:
																if len(self.db[nick]) < max_assets:
																	self.db[nick][from_symbol] -= amount
																	self.db[nick][to_symbol] = recv_amount
																	self.cleanup(nick)
																	self.sendmsg(chan, 'Trade successful!')
																else:
																	self.error(chan, f'You can\'t hold more than {max_assets} assets!')
														else:
															self.error(chan, 'Invalid trade pair!', 'Only BTC, ETH, & LTC can be traded for USD.')
													elif from_symbol in ('BTC','ETH') or to_symbol in ('BTC','ETH'):
														from_value = float([item for item in CMC.get() if from_symbol == item['symbol']][0]['price_usd'])
														to_value = float([item for item in CMC.get() if to_symbol == item['symbol']][0]['price_usd'])
														recv_amount = (fee_amount*from_value)/to_value
														if to_symbol in self.db[nick]:
															self.db[nick][from_symbol] -= amount
															self.db[nick][to_symbol] += recv_amount
															self.cleanup(nick)
															self.sendmsg(chan, 'Trade successful!')
														else:
															if len(self.db[nick]) < max_assets:
																self.db[nick][from_symbol] -= amount
																self.db[nick][to_symbol] = recv_amount
																self.cleanup(nick)
																self.sendmsg(chan, 'Trade successful!')
															else:
																self.error(chan, f'You can\'t hold more than {max_assets} assets!')
													else:
														self.error(chan, 'Invalid trade pair!')
												else:
													self.error(chan, 'Insufficient funds.')
											else:
												self.error(chan, 'Invalid amount argument.')
										else:
											self.error(chan, 'Insufficient funds.')
									else:
										self.error(chan, 'Invalid trade pair.')
								elif nick in self.verifying:
									self.error(chan, 'Your account is not verified yet!')
								else:
									self.error(chan, 'You don\'t have an account!')
							else:
								self.error(chan, 'Exchange is down for scheduled maintenance. Please try again later.')
						elif args[0] == '!value':
							amount = args[1]
							if get_float(amount):
								coin = args[2].upper()
								api  = [item for item in CMC.get() if coin == item['symbol']]
								if api:
									value = float(api[0]['price_usd'])*float(amount)
									if value < 0.01:
										self.sendmsg(chan, '{0} is worth {1}'.format(self.color(f'{amount} {coin}', white), self.color('${0:,.8f}'.format(value), light_blue)))
									else:
										self.sendmsg(chan, '{0} is worth {1}'.format(self.color(f'{amount} {coin}', white), self.color('${0:,.2f}'.format(value), light_blue)))
								else:
									self.error(chan, 'Invalid cryptocurrency name!', coin.lower())
							else:
								self.error(chan, 'Invalid amount!', amount)
					elif len(args) == 4:
						if args[0] == '!send':
							if not self.maintenance:
								if nick in self.db:
									total = 0
									for symbol in self.db[nick]:
										amount = self.db[nick][symbol]
										if symbol == 'USD':
											value = amount
										else:
											value = float([item for item in CMC.get() if symbol == item['symbol']][0]['price_usd'])*amount
										total += float(value)
									if total >= limit_send:
										receiver = args[1].lower()
										if receiver in self.db:
											amount = args[2].replace(',','')
											symbol = args[3].upper()
											if symbol in self.db[nick]:
												if get_float(amount) or (amount.startswith('$') and get_float(amount[1:])):
													if amount.startswith('$'):
														if symbol != 'USD':
															value = float([item for item in CMC.get() if symbol == item['symbol']][0]['price_usd'])
															amount = float(amount[1:])/value
															usd_amount = value*amount
														else:
															amount = float(amount[1:])
															value = amount
															usd_amount = amount
													else:
														if symbol != 'USD':
															value = float([item for item in CMC.get() if symbol == item['symbol']][0]['price_usd'])
															amount = float(amount)
															usd_amount = value*amount
														else:
															amount = float(amount)
															value = amount
															usd_amount = amount
													if usd_amount >= limit_trade and usd_amount > 0.0:
														recv_amount = amount-(amount*fee_send)
														if self.db[nick][symbol] >= amount:
															if symbol in self.db[receiver]:
																self.db[receiver][symbol] += recv_amount
																self.db[nick][symbol] -= amount
																self.cleanup(nick)
																self.sendmsg(receiver, '{0} just sent you {1} {2}!'.format(self.color(nick, light_blue), recv_amount, symbol))
																self.sendmsg(chan, 'Sent!')
															else:
																if len(self.db[nick]) < max_assets:
																	self.db[receiver][symbol] = recv_amount
																	self.db[nick][symbol] -= amount
																	self.cleanup(nick)
																	self.sendmsg(receiver, '{0} just sent you {1} {2}!'.format(self.color(nick, light_blue), recv_amount, symbol))
																	self.sendmsg(chan, 'Sent!')
																else:
																	self.error(chan, f'User can\'t hold more than {max_assets} assets!')
														else:
															self.error(chan, 'Insufficient funds.')
													else:
														self.error(chan, 'Invalid send amount.', f'${limit_trade} minimum')
												else:
													self.error(chan, 'Invalid send amount.')
											else:
												self.error(chan, 'Insufficient funds.')
										elif receiver in self.verifying:
											self.error(chan, 'User is not verified yet!')
										else:
											self.error(chan, 'User is not in the database.')
									else:
										self.error(chan, 'Insufficent funds!', f'${limit_send} minium')
								elif nick in self.verifying:
									self.sendmsg(chan, 'Your account is not verified yet!')
								else:
									self.error(chan, 'You don\'t have an account!')
							else:
								self.error(chan, 'Exchange is down for scheduled maintenance. Please try again later.')
				self.last = time.time()
		except Exception as ex:
			self.error(chan, 'Unknown error occured!', ex)

	def event_nick_in_use(self):
		error('The bot is already running or nick is in use.')

	def handle_events(self, data):
		args = data.split()
		if data.startswith('ERROR :Closing Link:'):
			raise Exception('Connection has closed.')
		elif args[0] == 'PING':
			self.raw('PONG ' + args[1][1:])
		elif args[1] == '001':
			self.event_connect()
		elif args[1] == '433':
			self.event_nick_in_use()
		elif args[1] == 'KICK':
			nick   = args[0].split('!')[0][1:]
			chan   = args[2]
			kicked = args[3]
			if chan == channel:
				self.event_kick(nick, chan, kicked)
		elif args[1] == 'PRIVMSG':
			nick = args[0].split('!')[0][1:]
			chan = args[2]
			msg  = data.split(f'{args[0]} PRIVMSG {chan} :')[1]
			if chan == channel:
				self.event_message(nick, chan, msg)

	def identify(self, nick, passwd):
		self.sendmsg('nickserv', f'identify {nick} {passwd}')

	def join_channel(self, chan, key=None):
		self.raw(f'JOIN {chan} {key}') if key else self.raw('JOIN ' + chan)

	def listen(self):
		while True:
			try:
				data = self.sock.recv(1024).decode('utf-8')
				for line in (line for line in data.split('\r\n') if line):
					debug(line)
					if len(line.split()) >= 2:
						self.handle_events(line)
			except (UnicodeDecodeError,UnicodeEncodeError):
				pass
			except Exception as ex:
				error('Unexpected error occured.', ex)
				break
		self.event_disconnect()

	def loop_backup(self):
		while True:
			try:
				time.sleep(21600) # 6H
				with open('bank.pkl', 'wb') as bank_file:
					pickle.dump(self.bank, bank_file, pickle.HIGHEST_PROTOCOL)
				with open('db.pkl', 'wb') as db_file:
					pickle.dump(self.db, db_file, pickle.HIGHEST_PROTOCOL)
				self.sendmsg(channel, self.color('Database backed up!', green))
			except Exception as ex:
				error('Error occured in the backup loop!', ex)

	def loop_maintenance(self):
		while True:
			try:
				time.sleep(random_int(864000, 2592000)) # 10D - 30D
				self.maintenance = True
				self.sendmsg(channel, self.color('The IRC Cryptocurrency Exchange is down for scheduled maintenance!', red))
				time.sleep(random_int(3600, 86400))   # 1H - 1D
				self.maintenance = False
				self.sendmsg(channel, self.color('Maintenance complete! The IRC Cryptocurrency Exchange is back online!', green))
			except Exception as ex:
				self.maintenance = False
				error('Error occured in the maintenance loop!', ex)
				time.sleep(900)

	def loop_verify(self):
		while True:
			try:
				verified = [nick for nick in self.verifying if time.time() - self.verifying[nick] >= 86400] # 1D
				for nick in verified:
					self.db[nick] = {'USD':init_funds}
					del self.verifying[nick]
					self.sendmsg(nick, f'Your account is now verified! Here is {condense_value(init_funds)} to start trading!')
					time.sleep(throttle_msg)
			except Exception as ex:
				error('Error occured in the verify loop!', ex)
			finally:
				time.sleep(3600) # 1H

	def mode(self, target, mode):
		self.raw(f'MODE {target} {mode}')

	def nick(self, nick):
		self.raw('NICK ' + nick)

	def raw(self, msg):
		self.sock.send(bytes(msg + '\r\n', 'utf-8'))

	def register(self):
		if network_password:
			self.raw('PASS ' + network_password)
		self.raw(f'USER {username} 0 * :{realname}')
		self.nick(nickname)

	def sendmsg(self, target, msg):
		self.raw(f'PRIVMSG {target} :{msg}')
		time.sleep(throttle_msg)

# Main
if proxy:
	try:
		import socks
	except ImportError:
		error_exit('Missing PySocks module! (https://pypi.python.org/pypi/PySocks)')
if use_ssl:
	import ssl
if currency_convert:
	if currency_convert.upper() not in ('AUD','BRL','CAD','CHF','CLP','CNY','CZK','DKK','EUR','GBP','HKD','HUF','IDR','ILS','INR','JPY','KRW','MXN','MYR','NOK','NZD','PHP','PKR','PLN','RUB','SEK','SGD','THB','TRY','TWD','ZAR'):
		error_exit('Invalid currency convert option!')
CMC = CoinMarketCap()
Bot = IRC()
Bot.run()
