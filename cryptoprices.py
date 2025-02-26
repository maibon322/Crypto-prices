import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackContext,
    CallbackQueryHandler,
    MessageHandler,
    Filters,
    ConversationHandler
)
import requests
import json
from datetime import datetime

# Configuration
BOT_TOKEN = 'YOUR_BOT_TOKEN'
COINGECKO_API_URL = 'https://api.coingecko.com/api/v3'
ADMIN_IDS = []  # Ajouter les IDs des administrateurs

# États pour la conversation d'admin
SELECTING_ACTION, SELECTING_RECIPIENT, WRITING_MESSAGE = range(3)

# Stockage simplifié (à remplacer par une base de données réelle pour la production)
users = {}
groups = {}
blocked = {'users': set(), 'groups': set()}

# Initialisation du logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

# Fonctions pour CoinGecko
def get_crypto_data(ticker):
    try:
        # Recherche des cryptos avec le ticker
        search_response = requests.get(f'{COINGECKO_API_URL}/search?query={ticker}').json()
        coins = [coin for coin in search_response['coins'] if coin['symbol'].lower() == ticker.lower()]
        
        if not coins:
            return None
            
        # Récupérer les données de marché pour les cryptos trouvées
        ids = [coin['id'] for coin in coins]
        markets_response = requests.get(
            f'{COINGECKO_API_URL}/coins/markets',
            params={
                'vs_currency': 'usd',
                'ids': ','.join(ids),
                'order_by': 'market_cap_desc'
            }
        ).json()
        
        if not markets_response:
            return None
        
        # Sélectionner la crypto avec la plus grande capitalisation
        selected = markets_response[0]
        
        # Récupérer les données détaillées
        detail_response = requests.get(
            f'{COINGECKO_API_URL}/coins/{selected["id"]}'
        ).json()
        
        return {
            'name': detail_response['name'],
            'symbol': detail_response['symbol'].upper(),
            'price': detail_response['market_data']['current_price']['usd'],
            '1h': detail_response['market_data']['price_change_percentage_1h_in_currency']['usd'],
            '24h': detail_response['market_data']['price_change_percentage_24h_in_currency']['usd'],
            '7d': detail_response['market_data']['price_change_percentage_7d_in_currency']['usd'],
            'market_cap': detail_response['market_data']['market_cap']['usd'],
            'last_updated': detail_response['market_data']['last_updated']
        }
    except Exception as e:
        logger.error(f"Erreur API CoinGecko: {e}")
        return None

# Commandes utilisateur
def price_command(update: Update, context: CallbackContext):
    if str(update.effective_chat.id) in blocked['groups'] or str(update.effective_user.id) in blocked['users']:
        return

    ticker = context.args[0].upper() if context.args else None
    if not ticker:
        update.message.reply_text("Veuillez spécifier un ticker (ex: /p BTC)")
        return

    data = get_crypto_data(ticker)
    if not data:
        update.message.reply_text("Cryptomonnaie non trouvée")
        return

    message = (
        f"🏷 {data['name']} ({data['symbol']})\n"
        f"💵 Prix: ${data['price']:,.2f}\n"
        f"📈 Variations:\n"
        f" 1h: {data['1h']:+.2f}%\n"
        f" 24h: {data['24h']:+.2f}%\n"
        f" 7j: {data['7d']:+.2f}%\n"
        f"🔄 Dernière maj: {data['last_updated'][11:19]} UTC"
    )

    keyboard = [[InlineKeyboardButton("🔄 Actualiser", callback_data=f"refresh_{data['symbol']}_{data['market_cap']}")]]
    update.message.reply_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def refresh_button(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    _, symbol, _ = query.data.split('_')
    data = get_crypto_data(symbol)
    
    if not data:
        query.edit_message_text("Données non disponibles")
        return

    message = (
        f"🏷 {data['name']} ({data['symbol']})\n"
        f"💵 Prix: ${data['price']:,.2f}\n"
        f"📈 Variations:\n"
        f" 1h: {data['1h']:+.2f}%\n"
        f" 24h: {data['24h']:+.2f}%\n"
        f" 7j: {data['7d']:+.2f}%\n"
        f"🔄 Dernière maj: {data['last_updated'][11:19]} UTC"
    )

    keyboard = [[InlineKeyboardButton("🔄 Actualiser", callback_data=f"refresh_{data['symbol']}_{data['market_cap']}")]]
    query.edit_message_text(
        text=message,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# Admin panel
def admin(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return

    keyboard = [
        [InlineKeyboardButton("👥 Utilisateurs", callback_data='admin_users')],
        [InlineKeyboardButton("👥 Groupes", callback_data='admin_groups')],
        [InlineKeyboardButton("🚫 Bloquer", callback_data='admin_block')],
        [InlineKeyboardButton("✉️ Envoyer message", callback_data='admin_send')]
    ]
    update.message.reply_text(
        "Panneau d'administration:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    return SELECTING_ACTION

def admin_action(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    if query.data == 'admin_users':
        message = "Utilisateurs ayant utilisé le bot:\n" + "\n".join(f"{uid}: {data['name']}" for uid, data in users.items())
        query.edit_message_text(message)
    elif query.data == 'admin_groups':
        message = "Groupes avec le bot:\n" + "\n".join(f"{gid}: {data['name']}" for gid, data in groups.items())
        query.edit_message_text(message)
    elif query.data == 'admin_block':
        query.edit_message_text("Entrez l'ID à bloquer (précédez par 'g' pour un groupe):")
        return SELECTING_RECIPIENT
    elif query.data == 'admin_send':
        query.edit_message_text("Entrez le destinataire (ID) et le message séparés par | :")
        return WRITING_MESSAGE

    return ConversationHandler.END

def block_user(update: Update, context: CallbackContext):
    recipient = update.message.text
    if recipient.startswith('g'):
        blocked['groups'].add(recipient[1:])
    else:
        blocked['users'].add(recipient)
    update.message.reply_text(f"🚫 {recipient} bloqué")
    return ConversationHandler.END

def send_message(update: Update, context: CallbackContext):
    parts = update.message.text.split('|')
    if len(parts) != 2:
        update.message.reply_text("Format invalide")
        return ConversationHandler.END

    recipient, message = parts
    try:
        context.bot.send_message(recipient.strip(), message.strip())
        update.message.reply_text("✅ Message envoyé")
    except Exception as e:
        update.message.reply_text(f"❌ Erreur: {e}")
    return ConversationHandler.END

def cancel(update: Update, context: CallbackContext):
    update.message.reply_text('Annulé')
    return ConversationHandler.END

# Track users/groups
def track_chat(update: Update, context: CallbackContext):
    chat = update.effective_chat
    if chat.type == 'private':
        users[str(chat.id)] = {'name': chat.full_name, 'last_seen': datetime.now()}
    else:
        groups[str(chat.id)] = {'name': chat.title, 'last_seen': datetime.now()}

def main():
    updater = Updater(BOT_TOKEN)
    dp = updater.dispatcher

    # Commandes utilisateur
    dp.add_handler(CommandHandler("p", price_command, pass_args=True))
    dp.add_handler(CallbackQueryHandler(refresh_button, pattern='^refresh_'))

    # Conversation admin
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('admin', admin)],
        states={
            SELECTING_ACTION: [CallbackQueryHandler(admin_action)],
            SELECTING_RECIPIENT: [MessageHandler(Filters.text & ~Filters.command, block_user)],
            WRITING_MESSAGE: [MessageHandler(Filters.text & ~Filters.command, send_message)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    dp.add_handler(conv_handler)

    # Track all messages
    dp.add_handler(MessageHandler(Filters.all, track_chat))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()