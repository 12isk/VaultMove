"""Generate vaultmove/app/i18n/vaultmove_fr.ts from the French table below.

    python tools/make_ts.py          # writes the .ts (strings without a translation are marked unfinished)
    pyside6-lrelease vaultmove/app/i18n/vaultmove_fr.ts   # CI compiles it to .qm
"""

from __future__ import annotations

import os
import sys
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from i18n_extract import ROOT, extract  # noqa: E402

FR = {
    "This is a Windows or app-data folder. VaultMove does not back up or remove system files.":
        "C’est un dossier de Windows ou de données d’applications. VaultMove ne sauvegarde ni ne supprime les fichiers système.",
    "Choose specific folders rather than the whole Windows drive.":
        "Choisissez des dossiers précis plutôt que tout le disque Windows.",
    "This folder is already in the list.": "Ce dossier est déjà dans la liste.",
    "This folder contains the backup itself (or is inside it).":
        "Ce dossier contient la sauvegarde elle-même (ou se trouve dedans).",
    "Backup status": "État de la sauvegarde",
    "Backup progress": "Progression de la sauvegarde",
    "Back Up Now": "Sauvegarder maintenant",
    "Start a backup now (Ctrl+B)": "Lancer une sauvegarde maintenant (Ctrl+B)",
    "Preview…": "Aperçu…",
    "Show what would be copied and freed, without changing anything":
        "Montrer ce qui serait copié et libéré, sans rien modifier",
    "Stop": "Arrêter",
    "Backup drive name": "Nom du disque de sauvegarde",
    "Backup drive usage": "Occupation du disque de sauvegarde",
    "Change…": "Changer…",
    "Remove originals not changed for": "Retirer les originaux inchangés depuis",
    "Days before freeing space": "Jours avant de libérer de l’espace",
    "Add a folder": "Ajouter un dossier",
    "Remove the selected folder": "Retirer le dossier sélectionné",
    "Folders to back up": "Dossiers à sauvegarder",
    "Activity log": "Journal d’activité",
    "Choose a folder to back up": "Choisir un dossier à sauvegarder",
    "Backup drive": "Disque de sauvegarde",
    "Free up space": "Libérer de l’espace",
    "Free up space on this PC": "Libérer de l’espace sur ce PC",
    "days": "jours",
    "They go to the Recycle Bin first.": "Ils passent d’abord par la Corbeille.",
    "They are deleted permanently (the copy stays on the backup drive).":
        "Ils sont supprimés définitivement (la copie reste sur le disque de sauvegarde).",
    "Off. VaultMove only copies; it never removes anything from this PC.":
        "Désactivé. VaultMove se contente de copier ; il ne retire jamais rien de ce PC.",
    "No folders yet. Click + to add one.": "Aucun dossier pour l’instant. Cliquez sur + pour en ajouter un.",
    "The preview could not be completed. See the activity log.":
        "L’aperçu n’a pas pu aboutir. Consultez le journal d’activité.",
    "Not connected": "Non connecté",
    "Connect the drive and VaultMove will back up automatically.":
        "Branchez le disque et VaultMove sauvegardera automatiquement.",
    "No backup drive chosen yet.": "Aucun disque de sauvegarde choisi pour l’instant.",
    "Stop backing up “%1”?\n\nCopies already on the backup drive are kept and can still be restored.":
        "Arrêter de sauvegarder « %1 » ?\n\nLes copies déjà présentes sur le disque de sauvegarde sont conservées et restent restaurables.",
    "This folder overlaps “%1”, which is already backed up.":
        "Ce dossier chevauche « %1 », qui est déjà sauvegardé.",
    "On. Originals are removed only after their copy on the backup drive is verified.":
        "Activé. Les originaux ne sont retirés qu’après vérification de leur copie sur le disque de sauvegarde.",
    "not available": "indisponible",
    "Preview not available: %1": "Aperçu indisponible : %1",
    "%1 free of %2": "%1 libres sur %2",
    "Not backed up yet": "Pas encore sauvegardé",
    "Next backup soon": "Prochaine sauvegarde bientôt",
    "Freeing up space…": "Libération d’espace…",
    "Set up VaultMove": "Configurer VaultMove",
    "Choose a backup drive to get started.": "Choisissez un disque de sauvegarde pour commencer.",
    "Backups paused": "Sauvegardes en pause",
    "Backup drive not connected": "Disque de sauvegarde non connecté",
    "Last backup needs attention": "La dernière sauvegarde demande votre attention",
    "Ready to back up": "Prêt à sauvegarder",
    "Your first backup will start soon.": "Votre première sauvegarde va bientôt commencer.",
    "A backup is running. Stop it and quit? Nothing will be lost; it continues next time.":
        "Une sauvegarde est en cours. L’arrêter et quitter ? Rien ne sera perdu ; elle reprendra la prochaine fois.",
    "Preparing preview…": "Préparation de l’aperçu…",
    "Backing up…": "Sauvegarde en cours…",
    "Last backup: %1": "Dernière sauvegarde : %1",
    "Next backup in %1 min": "Prochaine sauvegarde dans %1 min",
    "Backed up %1": "Sauvegardé %1",
    "Connect your backup drive, then try again.": "Branchez votre disque de sauvegarde, puis réessayez.",
    "Backup complete": "Sauvegarde terminée",
    "Some files were in use": "Certains fichiers étaient en cours d’utilisation",
    "Backup needs attention": "La sauvegarde demande votre attention",
    "%1 files checked, %2 copied": "%1 fichiers vérifiés, %2 copiés",
    "Space freed": "Espace libéré",
    "Connect “%1” to back up.": "Branchez « %1 » pour sauvegarder.",
    "Your files haven't been backed up for %1 days. Connect your backup drive.":
        "Vos fichiers n’ont pas été sauvegardés depuis %1 jours. Branchez votre disque de sauvegarde.",
    "%1 open files were skipped. Click Back Up Now to copy them using a snapshot.":
        "%1 fichiers ouverts ont été ignorés. Cliquez sur Sauvegarder maintenant pour les copier via un instantané.",
    "%1 files copied (%2).": "%1 fichiers copiés (%2).",
    "%1 freed on this PC.": "%1 libérés sur ce PC.",
    "%1 freed on this PC. Copies are safe on your backup drive.":
        "%1 libérés sur ce PC. Les copies sont en sécurité sur votre disque de sauvegarde.",
    "Backed up": "Sauvegardé",
    "Older copy kept": "Ancienne copie conservée",
    "Removed from this PC (copy verified)": "Retiré de ce PC (copie vérifiée)",
    "Restored": "Restauré",
    "Deleted on this PC": "Supprimé sur ce PC",
    "Back on this PC": "De retour sur ce PC",
    "Old version deleted": "Ancienne version supprimée",
    "Backup copy failed verification": "La copie de sauvegarde a échoué à la vérification",
    "Recovered after an interruption": "Récupéré après une interruption",
    "Recovered file kept": "Fichier récupéré conservé",
    "Every 15 minutes": "Toutes les 15 minutes",
    "Every 30 minutes": "Toutes les 30 minutes",
    "Every hour": "Toutes les heures",
    "Every 2 hours": "Toutes les 2 heures",
    "Every 4 hours": "Toutes les 4 heures",
    "Every 12 hours": "Toutes les 12 heures",
    "Once a day": "Une fois par jour",
    "Forever (thinned over time)": "Pour toujours (élaguées avec le temps)",
    "1 year": "1 an",
    "6 months": "6 mois",
    "3 months": "3 mois",
    "1 month": "1 mois",
    "Recycle Bin during the first week": "Corbeille pendant la première semaine",
    "Always use the Recycle Bin": "Toujours utiliser la Corbeille",
    "Delete permanently (copy stays on the backup drive)":
        "Supprimer définitivement (la copie reste sur le disque de sauvegarde)",
    "Copy to backup": "Copier vers la sauvegarde",
    "Free on this PC": "Libérer sur ce PC",
    "Free on a later run": "Libérer lors d’un prochain passage",
    "Preview": "Aperçu",
    "Everything": "Tout",
    "Files freed on this PC": "Fichiers libérés sur ce PC",
    "Files copied": "Fichiers copiés",
    "Freed on a later run": "Libérés lors d’un prochain passage",
    "Show": "Afficher",
    "Planned actions": "Actions prévues",
    "During your first week, removed files go to the Recycle Bin.":
        "Pendant votre première semaine, les fichiers retirés vont dans la Corbeille.",
    "Removed files are deleted permanently from this PC (Settings → Recycle Bin to change).":
        "Les fichiers retirés sont supprimés définitivement de ce PC (Réglages → Corbeille pour changer).",
    "I understand that originals will be removed from this PC after their copy is verified on the backup drive.":
        "Je comprends que les originaux seront retirés de ce PC après vérification de leur copie sur le disque de sauvegarde.",
    "Confirm": "Confirmer",
    "Step 1: look at the preview. Step 2: confirm and turn on.":
        "Étape 1 : consultez l’aperçu. Étape 2 : confirmez et activez.",
    "Turn On": "Activer",
    "Cancel": "Annuler",
    "Settings": "Réglages",
    "Back up:": "Sauvegarder :",
    "Back up when the backup drive is connected": "Sauvegarder quand le disque de sauvegarde est branché",
    "Start VaultMove with Windows": "Lancer VaultMove avec Windows",
    "Pause on battery below": "Pause sur batterie en dessous de",
    "Battery threshold": "Seuil de batterie",
    "Power:": "Alimentation :",
    "Run at low priority so the PC stays responsive": "Tourner en basse priorité pour que le PC reste réactif",
    "Copy files that are open (asks for administrator permission on Back Up Now)":
        "Copier les fichiers ouverts (demande l’autorisation administrateur lors de Sauvegarder maintenant)",
    "Open files:": "Fichiers ouverts :",
    "Keep older versions:": "Garder les anciennes versions :",
    "Freed files:": "Fichiers libérés :",
    "Same as Windows": "Comme Windows",
    "Language:": "Langue :",
    "Allow a backup drive on the same disk as my files (not recommended)":
        "Autoriser une sauvegarde sur le même disque que mes fichiers (déconseillé)",
    "Safety:": "Sécurité :",
    "Exclusions": "Exclusions",
    "Delete Old Versions…": "Supprimer les anciennes versions…",
    "Rebuild Index…": "Reconstruire l’index…",
    "Open Log Folder": "Ouvrir le dossier des journaux",
    "Delete Old Versions": "Supprimer les anciennes versions",
    "Delete older versions last changed more than this many days ago.\nThe latest copy of every file is always kept.":
        "Supprimer les anciennes versions modifiées pour la dernière fois il y a plus de ce nombre de jours.\nLa copie la plus récente de chaque fichier est toujours conservée.",
    "Rebuild the index by reading every file on the backup drive? This can take a long time. The old index is kept as a .broken file.":
        "Reconstruire l’index en relisant chaque fichier du disque de sauvegarde ? Cela peut être long. L’ancien index est conservé dans un fichier .broken.",
    "File history": "Historique du fichier",
    "Loading…": "Chargement…",
    "Nothing has been changed. This is what the next backup would do:":
        "Rien n’a été modifié. Voici ce que ferait la prochaine sauvegarde :",
    "Will be copied": "Sera copié",
    "Will be freed on this PC": "Sera libéré sur ce PC",
    "Freed after this backup is verified": "Libéré après vérification de cette sauvegarde",
    "VaultMove can remove files from this PC once they are safely on your backup drive. Before removing a file it re-reads both the original and the copy and checks they are identical. The backup drive then holds the only copy, so keep it safe.":
        "VaultMove peut retirer des fichiers de ce PC une fois qu’ils sont en sécurité sur votre disque de sauvegarde. Avant de retirer un fichier, il relit l’original et la copie et vérifie qu’ils sont identiques. Le disque de sauvegarde contient alors la seule copie : prenez-en soin.",
    "Connect your backup drive to see the preview.": "Branchez votre disque de sauvegarde pour voir l’aperçu.",
    "A backup is running. Try again when it has finished.":
        "Une sauvegarde est en cours. Réessayez quand elle sera terminée.",
    "Never back up (one pattern per line, e.g. *.iso or Projects/build/**):":
        "Ne jamais sauvegarder (un motif par ligne, p. ex. *.iso ou Projets/build/**) :",
    "A backup on the same disk as your files does not protect you if that disk fails, and VaultMove will never free up space on it. Allow it anyway?":
        "Une sauvegarde sur le même disque que vos fichiers ne vous protège pas si ce disque tombe en panne, et VaultMove n’y libérera jamais d’espace. L’autoriser quand même ?",
    "The new language is used after VaultMove restarts.":
        "La nouvelle langue sera utilisée au prochain démarrage de VaultMove.",
    "Connect the backup drive and wait for any backup to finish.":
        "Branchez le disque de sauvegarde et attendez la fin de toute sauvegarde en cours.",
    "When": "Quand",
    "What": "Quoi",
    "Details": "Détails",
    "The index is not available. Connect your backup drive.":
        "L’index n’est pas disponible. Branchez votre disque de sauvegarde.",
    "Action": "Action",
    "File": "Fichier",
    "Size": "Taille",
    "Show:": "Afficher :",
    "Only files not changed for at least": "Seulement les fichiers inchangés depuis au moins",
    "%1 files": "%1 fichiers",
    "Recycle Bin": "Corbeille",
    "deleted": "supprimé",
    "Deleted %1 old versions (%2).": "%1 anciennes versions supprimées (%2).",
    "Index rebuilt: %1 files, %2 older versions.": "Index reconstruit : %1 fichiers, %2 anciennes versions.",
    "Preview done: %1 files (%2) would be freed now, %3 more (%4) after this backup.":
        "Aperçu terminé : %1 fichiers (%2) seraient libérés maintenant, %3 de plus (%4) après cette sauvegarde.",
    "Settings (Ctrl+,)": "Réglages (Ctrl+,)",
    "Back Up": "Sauvegarde",
    "Browse && Restore": "Parcourir et restaurer",
    "VaultMove is still running": "VaultMove continue de fonctionner",
    "Backups continue in the background. Find VaultMove in the notification area.":
        "Les sauvegardes continuent en arrière-plan. VaultMove se trouve dans la zone de notification.",
    "On this PC": "Sur ce PC",
    "Backup drive only": "Sauvegarde uniquement",
    "Older version": "Ancienne version",
    "Name": "Nom",
    "Status": "État",
    "Modified": "Modifié",
    "Backed-up folder": "Dossier sauvegardé",
    "Up one folder (Backspace)": "Dossier parent (Retour arrière)",
    "Up one folder": "Dossier parent",
    "Search all versions…": "Rechercher dans toutes les versions…",
    "Search all versions": "Rechercher dans toutes les versions",
    "Files": "Fichiers",
    "Where Is It?": "Où est-il ?",
    "Show the history of the selected file": "Afficher l’historique du fichier sélectionné",
    "Restore To…": "Restaurer vers…",
    "Restore": "Restaurer",
    "Put the selected items back where they were (existing files are never overwritten)":
        "Remettre les éléments sélectionnés à leur place (les fichiers existants ne sont jamais écrasés)",
    "Restore to which folder?": "Restaurer dans quel dossier ?",
    "Restoring…": "Restauration…",
    "No backup index found yet. Connect your backup drive and run a backup.":
        "Aucun index de sauvegarde pour l’instant. Branchez votre disque de sauvegarde et lancez une sauvegarde.",
    "Add a folder on the Back Up page first.": "Ajoutez d’abord un dossier dans la page Sauvegarde.",
    "Nothing was backed up in this folder at that time.": "Rien n’était sauvegardé dans ce dossier à ce moment-là.",
    "Search results": "Résultats de recherche",
    "The backup drive is not connected: you are browsing the saved index. Connect the drive to restore.":
        "Le disque de sauvegarde n’est pas branché : vous parcourez l’index enregistré. Branchez le disque pour restaurer.",
    "Restore failed: %1": "Échec de la restauration : %1",
    "%1 selected": "%1 sélectionnés",
    "Restored %1 items (%2). Every file was checked against its backup.":
        "%1 éléments restaurés (%2). Chaque fichier a été comparé à sa sauvegarde.",
    "%1 were already identical and were left as they are.": "%1 étaient déjà identiques et ont été laissés tels quels.",
    "%1 were saved with “.restored” in the name because a file with the same name already existed.":
        "%1 ont été enregistrés avec « .restored » dans le nom car un fichier du même nom existait déjà.",
    "Restoring… %1 of %2": "Restauration… %1 sur %2",
    "%1 could not be restored:": "%1 n’ont pas pu être restaurés :",
    "Timeline": "Chronologie",
    "Scrub to see your files as they were. Up/Down keys move between backups.":
        "Faites défiler pour voir vos fichiers tels qu’ils étaient. Les flèches Haut/Bas passent d’une sauvegarde à l’autre.",
    "Now": "Maintenant",
    "Today": "Aujourd’hui",
    "Yesterday": "Hier",
    "Open VaultMove": "Ouvrir VaultMove",
    "Pause Backups": "Mettre les sauvegardes en pause",
    "Browse Backups": "Parcourir les sauvegardes",
    "Quit VaultMove": "Quitter VaultMove",
    "VaultMove": "VaultMove",
    "Resume Backups": "Reprendre les sauvegardes",
    "never": "jamais",
    "just now": "à l’instant",
    "yesterday": "hier",
    "1 minute ago": "il y a 1 minute",
    "1 hour ago": "il y a 1 heure",
    "%1 days ago": "il y a %1 jours",
    "%1 minutes ago": "il y a %1 minutes",
    "%1 hours ago": "il y a %1 heures",
    "Available drives": "Disques disponibles",
    "Choose a Folder…": "Choisir un dossier…",
    "Refresh": "Actualiser",
    "Use it anyway (not recommended: a disk failure would lose both copies)":
        "L’utiliser quand même (déconseillé : une panne du disque ferait perdre les deux copies)",
    "Choose the backup folder": "Choisir le dossier de sauvegarde",
    "Add a Folder…": "Ajouter un dossier…",
    "I understand that originals will be removed from this PC after their copy is verified on the backup drive (Recycle Bin during the first week).":
        "Je comprends que les originaux seront retirés de ce PC après vérification de leur copie sur le disque de sauvegarde (Corbeille pendant la première semaine).",
    "A preview is always shown before anything real happens.":
        "Un aperçu est toujours affiché avant toute action réelle.",
    "Back": "Retour",
    "Continue": "Continuer",
    "Choose your backup drive": "Choisissez votre disque de sauvegarde",
    "Use an external drive (USB disk or SSD). VaultMove recognises it by its identity, not its drive letter, and never writes backups anywhere else.":
        "Utilisez un disque externe (disque USB ou SSD). VaultMove le reconnaît par son identité, pas par sa lettre de lecteur, et n’écrit jamais de sauvegarde ailleurs.",
    "No drives found. Connect your backup drive and click Refresh.":
        "Aucun disque trouvé. Branchez votre disque de sauvegarde et cliquez sur Actualiser.",
    "Warning: this is the same physical disk as your files. If that disk fails, the backup is lost too, and VaultMove will never free up space on it.":
        "Attention : c’est le même disque physique que vos fichiers. Si ce disque tombe en panne, la sauvegarde est perdue aussi, et VaultMove n’y libérera jamais d’espace.",
    "Choose what to back up": "Choisissez quoi sauvegarder",
    "You can change this later on the Back Up page.": "Vous pourrez changer cela plus tard dans la page Sauvegarde.",
    "Free up space?": "Libérer de l’espace ?",
    "Optional. VaultMove can remove old files from this PC once a verified copy is on the backup drive. It is off unless you turn it on here.":
        "Facultatif. VaultMove peut retirer d’anciens fichiers de ce PC une fois qu’une copie vérifiée est sur le disque de sauvegarde. C’est désactivé tant que vous ne l’activez pas ici.",
    "Change backup drive": "Changer de disque de sauvegarde",
    "Start Backup": "Lancer la sauvegarde",
    "Future backups will go to the new drive. The old backup drive is left untouched and can still be browsed by choosing it again here.":
        "Les prochaines sauvegardes iront sur le nouveau disque. L’ancien disque de sauvegarde n’est pas modifié et peut encore être parcouru en le choisissant à nouveau ici.",
    "USB drive": "Disque USB",
    "Local disk": "Disque local",
    "Windows drive": "Disque de Windows",
    "removable": "amovible",
    "Free up space for files not changed for": "Libérer de l’espace pour les fichiers inchangés depuis",
    "Use This Drive": "Utiliser ce disque",
    "network drives are not supported": "les lecteurs réseau ne sont pas pris en charge",
    "A new backup will be created in %1.": "Une nouvelle sauvegarde sera créée dans %1.",
    "An existing VaultMove backup was found in %1. It will be used and nothing in it is deleted.":
        "Une sauvegarde VaultMove existante a été trouvée dans %1. Elle sera utilisée et rien n’y sera supprimé.",
    "%1 already contains other files. Choose an empty folder or a whole drive.":
        "%1 contient déjà d’autres fichiers. Choisissez un dossier vide ou un disque entier.",
    "%1 cannot be reached.": "%1 est inaccessible.",
    "First backup: %1 files (%2).": "Première sauvegarde : %1 fichiers (%2).",
    "Tick the confirmation above to continue with “Free up space” turned on.":
        "Cochez la confirmation ci-dessus pour continuer avec « Libérer de l’espace » activé.",
    "Show what would be copied and freed, without changing anything (Ctrl+P)":
        "Montrer ce qui serait copié et libéré, sans rien modifier (Ctrl+P)",
    "Stop the running backup (Ctrl+.)": "Arrêter la sauvegarde en cours (Ctrl+.)",
    "Add a folder (Ctrl+N)": "Ajouter un dossier (Ctrl+N)",
    "Remove the selected folder (Delete)": "Retirer le dossier sélectionné (Suppr)",
    "No folders yet": "Aucun dossier pour l’instant",
    "Add the folders you want to protect, or drop them here from Explorer.":
        "Ajoutez les dossiers à protéger, ou déposez-les ici depuis l’Explorateur.",
    "Drop folders here": "Déposez des dossiers ici",
    "Removed “%1”; its copies stay on the backup drive":
        "« %1 » retiré ; ses copies restent sur le disque de sauvegarde",
    "Added “%1”": "« %1 » ajouté",
    "Added %1 folders": "%1 dossiers ajoutés",
    "Backup complete: %1 files copied (%2).": "Sauvegarde terminée : %1 fichiers copiés (%2).",
    "General": "Général",
    "Keyboard shortcuts": "Raccourcis clavier",
    "Stop the running backup": "Arrêter la sauvegarde en cours",
    "Back Up page": "Page Sauvegarde",
    "Browse && Restore page": "Page Parcourir et restaurer",
    "Close the window (keeps running)": "Fermer la fenêtre (VaultMove continue)",
    "Open folder": "Ouvrir le dossier",
    "Move along the timeline": "Se déplacer sur la chronologie",
    "Clear the search": "Effacer la recherche",
    "Settings saved": "Réglages enregistrés",
    "Show the history of the selected file (Ctrl+I)": "Afficher l’historique du fichier sélectionné (Ctrl+I)",
    "Restore into a folder you choose (Ctrl+Shift+R)": "Restaurer dans un dossier de votre choix (Ctrl+Maj+R)",
    "Put the selected items back where they were (existing files are never overwritten) (Ctrl+R)":
        "Remettre les éléments sélectionnés à leur place (les fichiers existants ne sont jamais écrasés) (Ctrl+R)",
    "Select files or folders to restore them. Drag files out to copy them anywhere.":
        "Sélectionnez des fichiers ou des dossiers pour les restaurer. Faites glisser des fichiers pour les copier où vous voulez.",
    "Nothing to browse yet": "Rien à parcourir pour l’instant",
    "No backups yet": "Aucune sauvegarde pour l’instant",
    "Connect your backup drive and run a backup. Your files will appear here.":
        "Branchez votre disque de sauvegarde et lancez une sauvegarde. Vos fichiers apparaîtront ici.",
    "Could not read the index": "Impossible de lire l’index",
    "No matches": "Aucun résultat",
    "Nothing here at that time": "Rien ici à ce moment-là",
    "Nothing was backed up in this folder at that time. Try a later date on the timeline.":
        "Rien n’était sauvegardé dans ce dossier à ce moment-là. Essayez une date plus récente sur la chronologie.",
    "Search failed": "La recherche a échoué",
    "Nothing in any version matches “%1”.": "Aucune version ne correspond à « %1 ».",
    "This PC": "Ce PC",
    "Drive on this PC": "Disque de ce PC",
    "almost full": "presque plein",
    "Usage of %1": "Occupation de %1",
    "Check for Updates…": "Rechercher des mises à jour…",
    "Connects to GitHub only when you click": "Se connecte à GitHub uniquement quand vous cliquez",
    "VaultMove version %1": "VaultMove version %1",
    "Check for Updates": "Rechercher des mises à jour",
    "Checking GitHub for a newer version…": "Recherche d’une nouvelle version sur GitHub…",
    "Update status": "État de la mise à jour",
    "What's new": "Nouveautés",
    "Open Release Page": "Ouvrir la page de la version",
    "Close": "Fermer",
    "Download and Install": "Télécharger et installer",
    "Verified. Installing and restarting VaultMove…": "Vérifié. Installation et redémarrage de VaultMove…",
    "VaultMove updates": "Mises à jour de VaultMove",
    "VaultMove only contacts GitHub when you click Check for Updates. The download is checked against its published SHA-256 checksum before anything is installed. Your settings and backups are kept.":
        "VaultMove ne contacte GitHub que lorsque vous cliquez sur Rechercher des mises à jour. Le téléchargement est comparé à sa somme de contrôle SHA-256 publiée avant toute installation. Vos réglages et vos sauvegardes sont conservés.",
    "A backup is running. Install the update when it has finished.":
        "Une sauvegarde est en cours. Installez la mise à jour quand elle sera terminée.",
    "a backup started; try again when it has finished": "une sauvegarde a commencé ; réessayez quand elle sera terminée",
    "Could not check for updates: %1": "Impossible de rechercher des mises à jour : %1",
    "Version %1 is available.": "La version %1 est disponible.",
    "You are running from source: update with git pull.": "Vous utilisez le code source : mettez à jour avec git pull.",
    "This release has no download for your version yet.":
        "Cette version ne propose pas encore de téléchargement pour votre installation.",
    "Downloading %1…": "Téléchargement de %1…",
    "Downloading… %1": "Téléchargement… %1",
    "The update could not be installed: %1": "La mise à jour n’a pas pu être installée : %1",
    "You are using version %1.": "Vous utilisez la version %1.",
    "VaultMove is up to date (latest version: %1).": "VaultMove est à jour (dernière version : %1).",
    "synced by OneDrive or another cloud service: backed up, never freed":
        "synchronisé par OneDrive ou un autre service cloud : sauvegardé, jamais libéré",
    "Preparing preview… %1 files checked":"Préparation de l’aperçu… %1 fichiers vérifiés",
    "The preview could not be completed: %1": "L’aperçu n’a pas pu aboutir : %1",
    "Space freed: %1 now, %2 after the copies are verified on a later run.":
        "Espace libéré : %1 maintenant, %2 après vérification des copies lors d’un prochain passage.",
}


def write_ts(path: str) -> list[str]:
    strings = extract()
    missing = []
    out = ['<?xml version="1.0" encoding="utf-8"?>', "<!DOCTYPE TS>",
           '<TS version="2.1" language="fr_FR" sourcelanguage="en">', "<context>", "    <name>VaultMove</name>"]
    for s in strings:
        t = FR.get(s)
        out.append("    <message>")
        out.append(f"        <source>{escape(s)}</source>")
        if t is None:
            missing.append(s)
            out.append('        <translation type="unfinished"></translation>')
        else:
            out.append(f"        <translation>{escape(t)}</translation>")
        out.append("    </message>")
    out += ["</context>", "</TS>", ""]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out))
    return missing


if __name__ == "__main__":
    p = os.path.join(ROOT, "vaultmove", "app", "i18n", "vaultmove_fr.ts")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    miss = write_ts(p)
    print(f"wrote {p}; {len(miss)} untranslated")
    for m in miss:
        print("  MISSING:", repr(m))
