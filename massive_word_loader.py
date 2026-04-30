"""
Массовая загрузка английских слов из бесплатных источников
Добавляет тысячи новых слов в words_data.py
"""

import os
import sys
import re
import time
import json
import sqlite3
import requests
from datetime import datetime
from pathlib import Path


class MassiveWordLoader:
    def __init__(self):
        self.words_file = Path('words_data.py')
        self.db_file = Path('english_words.db')
        self.backup_dir = Path('backups')
        self.backup_dir.mkdir(exist_ok=True)

        # Множества существующих слов
        self.existing_words = set()
        self.existing_pairs = set()

        # Загружаем существующие слова
        self.load_existing_words()

        print(f"📊 Текущее количество слов: {len(self.existing_words)}")

    def load_existing_words(self):
        """Загружает все существующие слова"""
        # Из SQLite базы
        if self.db_file.exists():
            try:
                conn = sqlite3.connect(self.db_file)
                cursor = conn.cursor()
                cursor.execute('SELECT word, translation FROM words')
                for row in cursor.fetchall():
                    self.existing_words.add(row[0].lower().strip())
                    if len(row) > 1:
                        self.existing_pairs.add((row[0].lower().strip(), row[1].lower().strip()))
                conn.close()
            except Exception as e:
                print(f"⚠️ Ошибка чтения БД: {e}")

        # Из файла words_data.py
        try:
            if str(Path.cwd()) in sys.path:
                sys.path.remove(str(Path.cwd()))
            sys.path.insert(0, str(Path.cwd()))
            from words_data import WORDS_DATABASE
            for word_data in WORDS_DATABASE:
                self.existing_words.add(word_data[0].lower().strip())
                self.existing_pairs.add((word_data[0].lower().strip(), word_data[2].lower().strip()))
            print(f"   Из файла загружено: {len(WORDS_DATABASE)} слов")
        except Exception as e:
            print(f"⚠️ Ошибка чтения файла: {e}")

    def get_massive_word_list(self):
        """Возвращает огромный список слов для добавления"""

        # Категория 1: Существительные (200+ слов)
        nouns = [
            "abundance", "accessory", "accolade", "accordion", "acetate",
            "adage", "addendum", "adhesive", "adjunct", "adversary",
            "aerosol", "affidavit", "aggregate", "alchemy", "allegory",
            "alloy", "altitude", "amalgam", "ambience", "amethyst",
            "amulet", "anecdote", "animation", "annex", "anthem",
            "anthology", "antidote", "aperture", "apparatus", "aqueduct",
            "arbitrator", "archetype", "archipelago", "armament", "arsenal",
            "artisan", "ascension", "asphalt", "asteroid", "astrolabe",
            "atrocity", "attrition", "auditorium", "avalanche", "aviator",
            "backlash", "ballad", "barometer", "barricade", "basilica",
            "batch", "beacon", "bedrock", "beneficiary", "bequest",
            "bibliography", "bifurcation", "biopsy", "blizzard", "blueprint",
            "borough", "bouquet", "boycott", "bracelet", "breach",
            "brochure", "bronchitis", "buccaneer", "buffer", "bulletin",
            "bureaucracy", "cabaret", "cadence", "calibration", "camouflage",
            "capsule", "caravan", "carburetor", "carnival", "cartography",
            "cascade", "casino", "catalyst", "catastrophe", "cauldron",
            "cavalry", "censor", "chandelier", "chaos", "charisma",
            "chassis", "chromosome", "citadel", "clamp", "cliche",
            "coercion", "cohesion", "collateral", "colloquium", "combustion",
            "commotion", "compendium", "concoction", "condolence", "confiscation",
            "connoisseur", "constellation", "contraption", "convection", "cornucopia",
            "corridor", "covenant", "credenza", "criterion", "crucible",
            "culmination", "curator", "cylinder", "debris", "decathlon",
            "decoy", "deity", "delicacy", "demarcation", "demographics",
            "depot", "dermatology", "dessert", "detergent", "diabetes",
            "diagnosis", "diameter", "diarrhea", "diesel", "dilemma",
            "dioxide", "diploma", "discrepancy", "dissonance", "distillery",
            "docile", "dolphin", "dome", "dosage", "dossier",
            "drought", "duet", "dynasty", "eclipse", "ecosystem",
            "effigy", "elixir", "embargo", "ember", "emblem",
            "embroidery", "encyclopedia", "engraving", "ensemble", "enzyme",
            "epitome", "equation", "erosion", "escalator", "espionage",
            "etiquette", "euphemism", "evacuation", "excavation", "excerpt",
            "excrement", "exile", "exodus", "exorcism", "extract",
            "eyelash", "fabric", "facade", "faction", "famine",
            "fantasy", "feat", "ferment", "fertilizer", "festivity",
            "fetus", "fiasco", "figurine", "filament", "finances",
            "fission", "fixture", "flagship", "flask", "flora",
            "fluctuation", "foe", "folklore", "forfeit", "fortress",
            "fossil", "foyer", "franchise", "freight", "fresco",
            "friction", "fungus", "furnace", "fuselage", "galaxy",
            "galleon", "gallstone", "gangrene", "garnish", "gazelle",
            "gemstone", "genesis", "genetics", "genocide", "geology",
            "gesture", "ghetto", "giraffe", "glacier", "gland",
            "glossary", "glucose", "glycerin", "glyph", "gondola",
        ]

        # Категория 2: Глаголы (200+ слов)
        verbs = [
            "abdicate", "abolish", "abscond", "absorb", "abstain",
            "accede", "accentuate", "acclimate", "accommodate", "accost",
            "accredit", "accrue", "adhere", "adjudicate", "adorn",
            "adulterate", "aggregate", "agitate", "alleviate", "amalgamate",
            "amass", "ameliorate", "annex", "annotate", "antagonize",
            "appease", "applaud", "arbitrate", "articulate", "aspirate",
            "assassinate", "assimilate", "attune", "audit", "augment",
            "authorize", "avenge", "baffle", "baptize", "barricade",
            "beautify", "bequeath", "besiege", "betroth", "bifurcate",
            "blanch", "blemish", "bolster", "bombard", "boycott",
            "braise", "brandish", "browse", "brutalize", "budget",
            "burgeon", "calcify", "calibrate", "captivate", "careen",
            "cascade", "castigate", "catalyze", "caution", "censor",
            "certify", "chaperone", "cherish", "chisel", "choreograph",
            "circulate", "circumvent", "clamor", "cleanse", "coagulate",
            "coerce", "collaborate", "commemorate", "commend", "commiserate",
            "commute", "compel", "compensate", "compile", "concede",
            "conciliate", "condense", "condone", "confiscate", "conjoin",
            "conjure", "consecrate", "conserve", "consign", "console",
            "consolidate", "contaminate", "contemplate", "contend", "contort",
            "convene", "correlate", "corroborate", "covet", "cringe",
            "crucify", "culminate", "cultivate", "curate", "dawdle",
            "debilitate", "debrief", "decipher", "decode", "decompose",
            "deface", "defame", "deflate", "deflect", "degrade",
            "dehydrate", "delegate", "delineate", "demolish", "demote",
            "demystify", "denounce", "depict", "deplete", "deploy",
            "depreciate", "derail", "derive", "desecrate", "designate",
            "despise", "detain", "deter", "detonate", "deviate",
            "devour", "diagnose", "diffuse", "digress", "dilute",
            "disarm", "discern", "discredit", "disembark", "disfigure",
            "disgorge", "disguise", "disintegrate", "dislocate", "dismantle",
            "disorient", "disparage", "dispatch", "dispel", "dispense",
            "disperse", "disregard", "dissect", "disseminate", "dissipate",
            "dissolve", "dissonate", "distill", "distort", "diversify",
            "divert", "divulge", "domesticate", "donate", "douse",
            "dramatize", "drench", "duplicate", "dwarf", "ebb",
            "eclipse", "edify", "efface", "elaborate", "elate",
            "electrocute", "elevate", "elicit", "elongate", "elude",
            "emaciate", "emanate", "emancipate", "embargo", "embark",
            "embellish", "embezzle", "embody", "emboss", "embroider",
            "emigrate", "empathize", "empower", "emulate", "encapsulate",
            "enchant", "encircle", "encode", "encompass", "encrypt",
            "endanger", "endear", "endorse", "endow", "endure",
            "energize", "enforce", "engender", "engrave", "engulf",
            "enhance", "enlighten", "enlist", "enrage", "enrich",
            "enroll", "enshrine", "ensue", "entail", "entangle",
        ]

        # Категория 3: Прилагательные (200+ слов)
        adjectives = [
            "abhorrent", "abominable", "abortive", "abrasive", "abrupt",
            "absentminded", "absorbent", "abstemious", "abstruse", "absurd",
            "abundant", "abysmal", "academic", "accelerated", "accessible",
            "acclaimed", "accommodating", "accomplished", "accountable", "accredited",
            "acerbic", "acoustic", "acquiescent", "acrid", "acrimonious",
            "adamant", "adaptable", "addictive", "adept", "adjacent",
            "adorable", "adrenal", "adroit", "advantageous", "adventurous",
            "adversarial", "aerial", "affable", "affectionate", "affirmative",
            "affluent", "ageless", "aggravating", "aggregate", "aghast",
            "agile", "agonizing", "agreeable", "airy", "alarming",
            "alcoholic", "alert", "algebraic", "alienated", "aligned",
            "alimentary", "allegorical", "allergic", "alluring", "aloof",
            "alterable", "amateurish", "amazing", "ambidextrous", "ambiguous",
            "ambitious", "ambivalent", "amenable", "amiable", "amicable",
            "amorous", "amorphous", "amphibious", "ample", "amputated",
            "anachronistic", "analogous", "analytical", "anarchic", "anatomical",
            "ancestral", "anchored", "angelic", "anglicized", "anguished",
            "animated", "annoying", "anonymous", "antagonistic", "antecedent",
            "antediluvian", "antiquated", "antiseptic", "apathetic", "apologetic",
            "appalling", "appealing", "appetizing", "applicable", "appreciative",
            "apprehensive", "approachable", "appropriate", "aquatic", "arable",
            "arbitrary", "arcane", "archetypal", "architectural", "ardent",
            "arduous", "argumentative", "arid", "aristocratic", "aromatic",
            "arrogant", "articulate", "artificial", "artistic", "ascending",
            "aseptic", "ashen", "asinine", "aspiring", "assertive",
            "assiduous", "assorted", "astounding", "astringent", "astronomical",
            "astute", "asymmetrical", "athletic", "atrocious", "atrophied",
            "attentive", "attenuated", "attractive", "atypical", "audacious",
            "audible", "auspicious", "austere", "authentic", "authoritarian",
            "authoritative", "autistic", "autobiographical", "autocratic", "automatic",
            "autonomous", "avantgarde", "avaricious", "average", "aviation",
            "avid", "avoidable", "awakened", "aweinspiring", "awkward",
            "axiomatic", "azure", "babbling", "backhanded", "bacterial",
            "baffled", "balanced", "balding", "balmy", "banal",
            "baptized", "barbarian", "barbarous", "barefoot", "barren",
            "baseless", "bashful", "battered", "beaming", "bearable",
            "beatific", "bedridden", "befuddled", "believable", "bellicose",
            "belligerent", "beneficial", "benevolent", "benign", "bereaved",
            "berserk", "besieged", "bestial", "betrayed", "bewildered",
            "bewitching", "biased", "bifocal", "bilateral", "bilingual",
            "billowing", "biodegradable", "biographical", "biological", "bipartisan",
            "biting", "bitter", "bizarre", "blaring", "blasphemous",
            "blatant", "blazing", "bleached", "bleak", "blemished",
            "blended", "blessed", "blinding", "blissful", "blistering",
            "bloated", "bloodshot", "bloodthirsty", "blotchy", "blundering",
            "blunt", "blurred", "boastful", "bodacious", "bohemian",
            "boiling", "boisterous", "bombastic", "bookish", "booming",
            "boorish", "botanical", "bothersome", "bouncing", "boundless",
            "bountiful", "boyish", "braided", "brainy", "brash",
        ]

        # Объединяем все слова
        all_words = []

        for word in nouns:
            if word.lower() not in self.existing_words:
                all_words.append(word)

        for word in verbs:
            if word.lower() not in self.existing_words:
                all_words.append(word)

        for word in adjectives:
            if word.lower() not in self.existing_words:
                all_words.append(word)

        print(f"   Найдено слов для добавления: {len(all_words)}")
        return all_words

    def get_word_details(self, word):
        """Получает транскрипцию и перевод для слова"""
        # Пробуем API
        details = self.get_from_api(word)

        if not details:
            # Создаем базовую запись
            details = {
                'word': word,
                'transcription': f"[{word}]",
                'translation': word
            }

        return details

    def get_from_api(self, word):
        """Получает данные из бесплатного API словаря"""
        try:
            url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and len(data) > 0:
                    word_data = data[0]

                    # Транскрипция
                    transcription = f"[{word}]"
                    if 'phonetic' in word_data and word_data['phonetic']:
                        transcription = f"[{word_data['phonetic']}]"
                    elif 'phonetics' in word_data:
                        for p in word_data['phonetics']:
                            if 'text' in p and p['text']:
                                transcription = f"[{p['text']}]"
                                break

                    # Определение
                    definition = None
                    if 'meanings' in word_data:
                        for meaning in word_data['meanings']:
                            if 'definitions' in meaning and meaning['definitions']:
                                definition = meaning['definitions'][0]['definition']
                                break

                    if definition:
                        return {
                            'word': word,
                            'transcription': transcription,
                            'translation': definition
                        }
        except Exception:
            pass

        return None

    def add_words_to_file(self, words_data):
        """Добавляет слова в файл words_data.py"""
        if not words_data:
            return 0

        # Создаем бэкап
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = self.backup_dir / f'words_data_backup_{timestamp}.py'

        try:
            with open(self.words_file, 'r', encoding='utf-8') as source:
                with open(backup_file, 'w', encoding='utf-8') as target:
                    target.write(source.read())
            print(f"✅ Бэкап создан: {backup_file}")
        except Exception as e:
            print(f"⚠️ Ошибка бэкапа: {e}")

        # Читаем файл
        with open(self.words_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Находим конец списка
        last_bracket = content.rfind('\n]')
        if last_bracket == -1:
            last_bracket = content.rfind(']')

        if last_bracket == -1:
            print("❌ Не удалось найти конец списка")
            return 0

        # Добавляем слова
        current_date = datetime.now().strftime('%Y-%m-%d %H:%M')
        new_words_str = f"\n    # ==========================================\n"
        new_words_str += f"    # МАССОВОЕ ДОПОЛНЕНИЕ: {current_date}\n"
        new_words_str += f"    # ==========================================\n"

        added = 0
        for data in words_data:
            word = data['word']
            if word.lower() not in self.existing_words:
                transcription = data['transcription'].replace('"', '\\"').replace("'", "\\'")
                translation = data['translation'].replace('"', '\\"').replace("'", "\\'")[:100]
                new_words_str += f'    ("{word}", "{transcription}", "{translation}"),\n'
                self.existing_words.add(word.lower())
                added += 1

        if added == 0:
            print("❌ Нет новых слов для добавления")
            return 0

        # Сохраняем
        updated_content = content[:last_bracket] + new_words_str + '\n]'

        # Обновляем комментарий с количеством
        updated_content = updated_content.replace(
            "# Словарь общим объемом более 2500 слов",
            f"# Словарь общим объемом более {len(self.existing_words)} слов"
        )

        with open(self.words_file, 'w', encoding='utf-8') as f:
            f.write(updated_content)

        return added

    def add_words_to_database(self, words_data):
        """Добавляет слова в базу данных"""
        if not self.db_file.exists():
            return 0

        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        added = 0
        for data in words_data:
            try:
                cursor.execute(
                    'INSERT OR IGNORE INTO words (word, transcription, translation) VALUES (?, ?, ?)',
                    (data['word'], data['transcription'], data['translation'][:200])
                )
                if cursor.rowcount > 0:
                    added += 1
            except Exception:
                pass

        conn.commit()
        conn.close()
        return added

    def load_massive(self, batch_size=100):
        """Загружает большую партию слов"""
        print(f"\n{'=' * 60}")
        print(f"🚀 МАССОВАЯ ЗАГРУЗКА СЛОВ")
        print(f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'=' * 60}")

        # Получаем список новых слов
        new_words = self.get_massive_word_list()

        if not new_words:
            print("ℹ️ Все возможные слова уже добавлены")
            return 0

        print(f"\n📝 Начинаю загрузку {min(len(new_words), batch_size)} слов...")

        # Обрабатываем слова пакетами
        words_data = []
        processed = 0

        for word in new_words[:batch_size]:
            processed += 1
            if processed % 20 == 0:
                print(f"   Прогресс: {processed}/{min(len(new_words), batch_size)}")

            details = self.get_word_details(word)
            if details:
                words_data.append(details)

            time.sleep(0.2)  # Задержка для API

        # Добавляем в файл
        file_added = self.add_words_to_file(words_data)
        print(f"\n📄 Добавлено в файл: {file_added}")

        # Добавляем в базу данных
        db_added = self.add_words_to_database(words_data)
        print(f"🗄 Добавлено в БД: {db_added}")

        total = max(file_added, db_added)
        print(f"\n✅ Всего добавлено: {total} новых слов")
        print(f"📚 Общее количество слов: {len(self.existing_words)}")

        return total


def main():
    """Основная функция"""
    loader = MassiveWordLoader()

    print(f"\n📚 Текущая база: {len(loader.existing_words)} слов")
    print(f"🔮 После загрузки будет: ~{len(loader.existing_words) + 600} слов")

    # Запрашиваем количество
    try:
        count = input("\nСколько слов загрузить? (Enter = 200): ").strip()
        count = int(count) if count else 200
    except ValueError:
        count = 200

    # Запускаем загрузку
    added = loader.load_massive(batch_size=count)

    if added > 0:
        print(f"\n🎉 Успешно! Добавлено {added} слов")
        print(f"📚 Теперь в базе: {len(loader.existing_words)} слов")
        print(f"\n💡 Перезапустите бота: python bot.py")
    else:
        print("\nℹ️ Новых слов не найдено")


if __name__ == "__main__":
    main()
