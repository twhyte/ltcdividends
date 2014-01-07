import socket
import sys
import argparse
import csv
import time
from bitcoinrpc.authproxy import AuthServiceProxy, JSONRPCException
from decimal import Decimal, getcontext, ROUND_DOWN

CONFIG = {}

CONFIG["config1"] = {
    "username": "USER",
    "password": "PASS",
    "wallet_passphrase": "WALLETPASSPHRASE",
    "port": 8332,
    "symbol": "LTC",
    "min_confirms": 0,
}

#To configure the script to work with multiple coin clients, add extra config blocks
#similar to the below, and use the --config command line switch to pick one
#e.g. --config=btc_config

#CONFIG["btc_config"] = {
#    "username": "ANOTHER_USERNAME",
#    "password": "ANOTHER_PASSWORD",
#    "port": 8333,
#    "symbol": "BTC",
#    "min_confirms": 0,
#}

DEBUG = False

class DividendPayer(object):
    def __init__(self, username, password, port, symbol, min_confirms, wallet_passphrase):
        self.symbol = symbol
        self.min_confirms = min_confirms
        self.coin_client = AuthServiceProxy("http://%s:%s@127.0.0.1:%s" % (username, password, port))
        self.shareholders = []
        self.total_shares = 0
        self.num_shareholders = 0
        self.payment_total = Decimal(0)
        self.payments_to_make = {}
        if not self.check_client_connection():
            print "Error: Failed to connect or authenticate with the %s client. Please check it's running and configured correctly." % self.symbol
            sys.exit(1)
        if wallet_passphrase:
            self.coin_client.walletpassphrase(wallet_passphrase,999)
    def check_client_connection(self):
        try:
            test = self.coin_client.getinfo()
            return True
        except socket.error:
            return False
        except ValueError:
            return False
    def calculate_and_confirm(self, amount, confirm=True):
        getcontext().rounding = ROUND_DOWN
        print "The following amounts will be paid: -"
        for shareholder in self.shareholders:
            if not shareholder['payment_address']:
                payment = None
                print "%s - Nothing (no payment address set)" % shareholder['email']                
            else:
                payment = (Decimal(shareholder["shares"]) / Decimal(self.total_shares)) * amount
                self.payments_to_make[shareholder['payment_address']] = float(payment) #Decimals aren't JSON serialisable :(
                self.payment_total += payment
                print "%s [%s] - %.8f %s" % (shareholder['email'],shareholder['payment_address'],payment,self.symbol)
        if confirm:
            yes = set(['yes','y'])
            no = set(['no','n'])
            while(True):
                print "Should I make these payments for you now? Y/N. Please check them carefully first and ensure you have enough additional balance to cover any transaction fees."
                choice = raw_input().lower()
                if choice in no:
                    print "Exiting"
                    sys.exit(1)
                elif choice in yes:
                    break
    def aggregate_wallet_balances(self):
        accounts = self.coin_client.listaccounts(self.min_confirms)
        print "Aggregating wallet subaccount balances..."
        if DEBUG:
            print "Accounts prior to balance aggregation: -"
            print accounts
        for account, balance in accounts.iteritems():
            if not account:
                continue
            if balance > 0:
                if DEBUG:
                    print "Aggregating balance from account %s into main wallet (%s %s)" % (account, balance, self.symbol)
                self.coin_client.move(account,"",float(balance),self.min_confirms,"Dividend tool balance aggregation")
            elif balance < 0:
                if DEBUG:
                    print "Aggregating balance from main wallet into account %s (%s %s)" % (account, balance, self.symbol)
                self.coin_client.move("",account,float(-balance),self.min_confirms,"Dividend tool balance aggregation")
            time.sleep(0.2)
        print "Waiting 5 seconds for client to catch up following balance aggregation..."
        time.sleep(5)
        if DEBUG:
            print "Accounts following balance aggregation: -"
            print self.coin_client.listaccounts(self.min_confirms)
    def make_payments(self):
        self.aggregate_wallet_balances()
        balance = self.coin_client.getbalance("",self.min_confirms)
        if balance < self.payment_total:
            print "Error: Your account balance is too low for these payments to be made"
            sys.exit(1)
        try:
            self.coin_client.sendmany("",self.payments_to_make,self.min_confirms,"Dividend tool payment")
            print "Payments have been sent"
        except JSONRPCException as e:
            print "Error sending payments: %s" % e.error['message']
    def read_csv(self,filename):
        with open(filename, 'rb') as csvfile:
            reportreader = csv.reader(csvfile)
            for row in reportreader:
                if len(row) != 3:
                    print "Skipping row: %s" % row
                    continue
                email, payment_address, shares = row
                shares = int(shares)
                self.shareholders.append({"email": email, "payment_address": payment_address, "shares": shares})
        for shareholder in self.shareholders:
            self.total_shares += shareholder["shares"]
            self.num_shareholders += 1
        print "Read details on %s shareholders and %s total shares from CSV" % (self.num_shareholders, self.total_shares)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pay dividends to security holders imported from an LTC Global/BTC Trading Co. style shareholder report CSV [email,payment address,number of shares] in proportion to their holdings")
    parser.add_argument("filename", help="Path to shareholder report CSV")
    parser.add_argument("amount", help="Total amount of dividends to pay (will be split between shareholders)", type=Decimal)
    parser.add_argument("--noconfirm", help="Skip manual confirmation (automated use)", action="store_true")
    parser.add_argument("--config", help="Use the named configuration (only required for use with multiple different coin clients)", type=str)
    args = parser.parse_args()
    if not args.config:
        if len(CONFIG)==1:
            args.config = CONFIG.keys()[0]
        else:
            print "You must use the --config switch to choose a configuration when multiple configs are defined"
            sys.exit(1)
    if not args.config in CONFIG:
        print "Invalid configuration: %s" % args.config
        sys.exit(1)
    cfg = CONFIG[args.config]
    print "Using configuration: %s" % cfg
    payer = DividendPayer(username=cfg["username"],password=cfg["password"],port=cfg["port"],symbol=cfg["symbol"],min_confirms=cfg["min_confirms"],wallet_passphrase=cfg["wallet_passphrase"])
    payer.read_csv(args.filename)
    if args.noconfirm:
        payer.calculate_and_confirm(args.amount, confirm=False)
    else:
        payer.calculate_and_confirm(args.amount, confirm=True)
    payer.coin_client.walletpassphrase(wallet_passphrase,999) # refresh walletpassphrase
    payer.make_payments()
