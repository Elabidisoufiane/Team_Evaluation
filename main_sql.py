import streamlit as st
import json
from typing import Dict, List, Any, Union
import random
import mysql.connector
from datetime import datetime
import hashlib

# Sample quiz data with all question types
SAMPLE_QUIZ_DATA = json.load(open("questions.json", "r", encoding="utf-8"))

# Default images for each item (you can replace these with your actual image URLs)
DEFAULT_IMAGES = [
    "matier.png",
    "metier.png", 
    "moule.png",
    "peripherique.png",
    "machine.png",
    "qualite.png"
]

# Database configuration
DB_CONFIG = {
    'host': '127.0.0.1',
    'user': 'root',
    'password': 'root123',
    'database': 'quiz_db2',
    'charset': 'utf8mb4',
    'collation': 'utf8mb4_unicode_ci'
}

class DatabaseManager:
    def __init__(self, config):
        self.config = config
        self.connection = None
    
    def connect(self):
        """Establish database connection"""
        try:
            self.connection = mysql.connector.connect(**self.config)
            return True
        except mysql.connector.Error as err:
            st.error(f"Erreur de connexion à la base de données: {err}")
            return False
    
    def disconnect(self):
        """Close database connection"""
        if self.connection and self.connection.is_connected():
            self.connection.close()
    
    def create_tables(self):
        """Create necessary tables if they don't exist"""
        if not self.connect():
            return False
        
        cursor = self.connection.cursor()
        
        # Create users table
        create_users_table = """
        CREATE TABLE IF NOT EXISTS users (
            user_id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(255) NOT NULL,
            first_evaluation_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            total_evaluations INT DEFAULT 0,
            INDEX idx_username (username)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """
        
        # Create evaluations table
        create_evaluations_table = """
        CREATE TABLE IF NOT EXISTS evaluations (
            evaluation_id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            item_name VARCHAR(500) NOT NULL,
            total_questions INT NOT NULL,
            correct_answers INT NOT NULL,
            score_percentage DECIMAL(5,2) NOT NULL,
            evaluation_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            duration_minutes INT DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            INDEX idx_user_item (user_id, item_name),
            INDEX idx_evaluation_date (evaluation_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """
        
        # Create question_results table for detailed analysis
        create_question_results_table = """
        CREATE TABLE IF NOT EXISTS question_results (
            result_id INT AUTO_INCREMENT PRIMARY KEY,
            evaluation_id INT NOT NULL,
            question_number INT NOT NULL,
            question_text TEXT NOT NULL,
            question_type VARCHAR(50) NOT NULL,
            is_correct BOOLEAN NOT NULL,
            user_answer TEXT,
            correct_answer TEXT,
            score_points DECIMAL(3,2) NOT NULL,
            FOREIGN KEY (evaluation_id) REFERENCES evaluations(evaluation_id) ON DELETE CASCADE,
            INDEX idx_evaluation_question (evaluation_id, question_number),
            INDEX idx_question_type (question_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """
        
        # Create item_statistics table for aggregated stats
        create_item_stats_table = """
        CREATE TABLE IF NOT EXISTS item_statistics (
            stat_id INT AUTO_INCREMENT PRIMARY KEY,
            item_name VARCHAR(500) NOT NULL,
            total_attempts INT DEFAULT 0,
            average_score DECIMAL(5,2) DEFAULT 0,
            total_correct_answers INT DEFAULT 0,
            total_questions_attempted INT DEFAULT 0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY unique_item (item_name)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """
        
        try:
            cursor.execute(create_users_table)
            cursor.execute(create_evaluations_table)
            cursor.execute(create_question_results_table)
            cursor.execute(create_item_stats_table)
            self.connection.commit()
            cursor.close()
            self.disconnect()
            return True
        except mysql.connector.Error as err:
            st.error(f"Erreur lors de la création des tables: {err}")
            cursor.close()
            self.disconnect()
            return False
    
    def get_or_create_user(self, username):
        """Get user ID or create new user"""
        if not self.connect():
            return None
        
        cursor = self.connection.cursor()
        
        # Check if user exists
        cursor.execute("SELECT user_id, total_evaluations FROM users WHERE username = %s", (username,))
        result = cursor.fetchone()
        
        if result:
            user_id, total_evals = result
            # Update total evaluations count
            cursor.execute("UPDATE users SET total_evaluations = %s WHERE user_id = %s", 
                         (total_evals + 1, user_id))
            self.connection.commit()
        else:
            # Create new user
            cursor.execute("INSERT INTO users (username, total_evaluations) VALUES (%s, %s)", 
                         (username, 1))
            self.connection.commit()
            user_id = cursor.lastrowid
        
        cursor.close()
        self.disconnect()
        return user_id
    
    def save_evaluation_results(self, user_id, item_name, questions_data, user_answers, results):
        """Save complete evaluation results to database"""
        if not self.connect():
            return False
        
        cursor = self.connection.cursor()
        
        try:
            # Calculate overall statistics
            total_questions = len(questions_data)
            correct_count = sum(1 for r in results if r['correct'])
            total_score = sum(r['score'] for r in results)
            score_percentage = (total_score / total_questions) * 100
            
            # Insert evaluation record
            cursor.execute("""
                INSERT INTO evaluations (user_id, item_name, total_questions, correct_answers, score_percentage)
                VALUES (%s, %s, %s, %s, %s)
            """, (user_id, item_name, total_questions, correct_count, score_percentage))
            
            evaluation_id = cursor.lastrowid
            
            # Insert detailed question results
            for i, (question_data, result) in enumerate(zip(questions_data, results)):
                user_answer_str = str(user_answers.get(i, "Non répondu"))
                correct_answer_str = str(self.get_correct_answer_string(question_data))
                
                cursor.execute("""
                    INSERT INTO question_results 
                    (evaluation_id, question_number, question_text, question_type, is_correct, 
                     user_answer, correct_answer, score_points)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (evaluation_id, i + 1, question_data['question'], question_data['type'],
                     result['correct'], user_answer_str, correct_answer_str, result['score']))
            
            # Update item statistics
            self.update_item_statistics(item_name, total_questions, correct_count, score_percentage)
            
            self.connection.commit()
            cursor.close()
            self.disconnect()
            return True
            
        except mysql.connector.Error as err:
            st.error(f"Erreur lors de la sauvegarde: {err}")
            self.connection.rollback()
            cursor.close()
            self.disconnect()
            return False
    
    def get_correct_answer_string(self, question_data):
        """Get correct answer as string for storage"""
        q_type = question_data['type']
        
        if q_type == 'multiple_choice':
            return f"Option {question_data['correct_option']}"
        elif q_type == 'multiple_select':
            return f"Options: {question_data['correct_options']}"
        elif q_type == 'matching':
            return str(question_data['correct_answers'])
        elif q_type == 'true_false':
            return "Vrai" if question_data['correct_answer'] else "Faux"
        elif q_type == 'calculation':
            return f"{question_data['correct_answer']} {question_data.get('unit', '')}"
        else:
            return "N/A"
    
    def update_item_statistics(self, item_name, total_questions, correct_count, score_percentage):
        """Update aggregated statistics for an item"""
        cursor = self.connection.cursor()
        
        # Check if item statistics exist
        cursor.execute("SELECT * FROM item_statistics WHERE item_name = %s", (item_name,))
        result = cursor.fetchone()
        
        if result:
            # Update existing statistics
            cursor.execute("""
                UPDATE item_statistics 
                SET total_attempts = total_attempts + 1,
                    total_correct_answers = total_correct_answers + %s,
                    total_questions_attempted = total_questions_attempted + %s,
                    average_score = (
                        SELECT AVG(score_percentage) 
                        FROM evaluations 
                        WHERE item_name = %s
                    )
                WHERE item_name = %s
            """, (correct_count, total_questions, item_name, item_name))
        else:
            # Create new item statistics
            cursor.execute("""
                INSERT INTO item_statistics 
                (item_name, total_attempts, average_score, total_correct_answers, total_questions_attempted)
                VALUES (%s, %s, %s, %s, %s)
            """, (item_name, 1, score_percentage, correct_count, total_questions))
        
        cursor.close()

class QuizApp:
    def __init__(self):
        # Initialize session state variables
        if 'user_name' not in st.session_state:
            st.session_state.user_name = ""
        if 'name_submitted' not in st.session_state:
            st.session_state.name_submitted = False
        if 'selected_item' not in st.session_state:
            st.session_state.selected_item = None
        if 'current_question' not in st.session_state:
            st.session_state.current_question = 0
        if 'user_answers' not in st.session_state:
            st.session_state.user_answers = {}
        if 'quiz_completed' not in st.session_state:
            st.session_state.quiz_completed = False
        if 'quiz_data' not in st.session_state:
            st.session_state.quiz_data = SAMPLE_QUIZ_DATA
        if 'evaluation_results' not in st.session_state:
            st.session_state.evaluation_results = []
        if 'db_manager' not in st.session_state:
            st.session_state.db_manager = DatabaseManager(DB_CONFIG)
        
        # Initialize database tables
        if 'db_initialized' not in st.session_state:
            st.session_state.db_manager.create_tables()
            st.session_state.db_initialized = True
        
        # New: Initialize the list for completed quizzes
        if 'completed_quizzes' not in st.session_state:
            st.session_state.completed_quizzes = []

    def render_name_input(self):
        """Render the name input screen"""
        st.markdown("""
        <div style='text-align: center; padding: 2rem;'>
            <h1 style='color: #1f77b4; margin-bottom: 2rem;'>🎓 Bienvenue au Quiz d'Évaluation</h1>
            <p style='font-size: 1.2rem; margin-bottom: 2rem;'>Veuillez entrer votre nom pour commencer</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Center the input field
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            # Replace st.text_input with st.selectbox
            # You need a list of names for the selectbox.
            # For this example, let's use a dummy list.
            # In a real application, you would load these names from your database.
            user_names_list = ["tech1", "tech2", "tech3", "tech4", "tech5", "tech6", "tech7", "tech8", "tech9", "tech10"] 
            
            name = st.selectbox(
                "Votre nom complet:",
                options=user_names_list,
                index=None,  # This allows for no default selection
                placeholder="Sélectionnez votre nom"
            )
            
            if st.button("Commencer le Quiz", use_container_width=True, type="primary"):
                if name:  # The condition now checks if a name has been selected (not None)
                    st.session_state.user_name = name
                    st.session_state.name_submitted = True
                    st.rerun()
                else:
                    st.error("Veuillez sélectionner votre nom pour continuer.")

    def render_item_selection(self):
        """Render the item selection screen with images"""
        st.markdown(f"""
        <div style='text-align: center; padding: 1rem;'>
            <h1 style='color: #1f77b4;'>Bonjour {st.session_state.user_name}! 👋</h1>
            <p style='font-size: 1.1rem; margin-bottom: 2rem;'>Choisissez un domaine d'évaluation :</p>
        </div>
        """, unsafe_allow_html=True)

        # Create a grid layout for items
        quiz_data = st.session_state.quiz_data
        
        # Display items in rows of 2 or 3 columns
        items_per_row = 3 if len(quiz_data) > 4 else 2
        
        # Retrieve the list of completed quizzes from session state
        completed_quizzes = st.session_state.get('completed_quizzes', [])
        
        for i in range(0, len(quiz_data), items_per_row):
            cols = st.columns(items_per_row)
            
            for j, col in enumerate(cols):
                if i + j < len(quiz_data):
                    item_index = i + j
                    item = quiz_data[item_index]
                    item_title = item["item"]
                    
                    # Check if the item is in the list of completed quizzes
                    is_completed = item_title in completed_quizzes

                    with col:
                        # Path to image inside your "images" folder
                        image_path = f"images/{DEFAULT_IMAGES[item_index % len(DEFAULT_IMAGES)]}"
                        
                        # Display image with fixed width
                        st.image(image_path, width=500)

                        st.markdown(f"""
                        <h3 style="text-align:center;">{item_title}</h3>
                        """, unsafe_allow_html=True)
                        
                        # Conditionally change the button label and state
                        button_label = "✅ Évaluation terminée" if is_completed else "Commencer l'évaluation"
                        button_type = "secondary" if is_completed else "primary"

                        if st.button(
                            button_label,
                            key=f"select_item_{item_index}",
                            use_container_width=True,
                            disabled=is_completed,  # Disable the button if the quiz is completed
                            type=button_type
                        ):
                            st.session_state.selected_item = item_index
                            st.session_state.current_question = 0
                            st.session_state.user_answers = {}
                            st.session_state.quiz_completed = False
                            st.session_state.evaluation_results = []
                            st.rerun()

        # Add a logout button
        st.markdown("---")
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            if st.button("🚪 Changer d'utilisateur", use_container_width=True):
                # Reset all session state
                for key in list(st.session_state.keys()):
                    if key not in ['db_manager', 'db_initialized']:
                        del st.session_state[key]
                st.rerun()

    def render_multiple_choice(self, question_data: Dict, q_id: str) -> Any:
        """Render multiple choice question"""
        options = [
            question_data.get('option1', ''),
            question_data.get('option2', ''),
            question_data.get('option3', ''),
            question_data.get('option4', '')
        ]
        
        selected = st.radio(
            "Choisissez une réponse:",
            options,
            key=f"mc_{q_id}",
            index=None
        )
        
        if selected:
            return options.index(selected) + 1
        return None

    def render_multiple_select(self, question_data: Dict, q_id: str) -> List[int]:
        """Render multiple select question"""
        options = question_data['options']
        min_sel = question_data.get('min_selections', 1)
        max_sel = question_data.get('max_selections', len(options))
        
        st.info(f"Sélectionnez entre {min_sel} et {max_sel} réponses")
        
        selected_indices = []
        for i, option in enumerate(options):
            if st.checkbox(option, key=f"ms_{q_id}_{i}"):
                selected_indices.append(i + 1)
        
        return selected_indices

    def render_matching(self, question_data: Dict, q_id: str) -> Dict[str, str]:
        """Render matching question"""
        options = question_data['options']
        categories = list(set(question_data['correct_answers'].values()))
        
        st.info(f"Attribuez chaque caractéristique à une catégorie: {', '.join(categories)}")
        
        answers = {}
        for i, option in enumerate(options):
            selected_cat = st.selectbox(
                option,
                [""] + categories,
                key=f"match_{q_id}_{i}"
            )
            if selected_cat:
                answers[option] = selected_cat
        
        return answers

    def render_true_false(self, question_data: Dict, q_id: str) -> bool:
        """Render true/false question"""
        selected = st.radio(
            "Choisissez votre réponse:",
            ["Vrai", "Faux"],
            key=f"tf_{q_id}",
            index=None
        )
        
        if selected:
            return selected == "Vrai"
        return None

    def render_range_input(self, question_data: Dict, q_id: str) -> Dict[str, Dict[str, float]]:
        """Render range input question"""
        materials = question_data['materials']
        ranges = {}
        
        st.info("Entrez les températures minimales et maximales pour chaque matière")
        
        for material in materials:
            col1, col2 = st.columns(2)
            with col1:
                min_temp = st.number_input(
                    f"{material} - Temp Min (°C)",
                    key=f"range_min_{q_id}_{material}",
                    value=0,
                    step=10
                )
            with col2:
                max_temp = st.number_input(
                    f"{material} - Temp Max (°C)",
                    key=f"range_max_{q_id}_{material}",
                    value=100,
                    step=10
                )
            
            if min_temp < max_temp:
                ranges[material] = {"min": min_temp, "max": max_temp}
        
        return ranges

    def render_ordering(self, question_data: Dict, q_id: str) -> List[int]:
        """Render ordering question"""
        items = question_data['items']
        st.info("Numérotez les étapes dans l'ordre chronologique (1, 2, 3, ...)")
        
        order = {}
        for i, item in enumerate(items):
            position = st.selectbox(
                item,
                [""] + list(range(1, len(items) + 1)),
                key=f"order_{q_id}_{i}"
            )
            if position:
                order[i] = position
        
        # Convert to list format
        if len(order) == len(items):
            sorted_items = sorted(order.items(), key=lambda x: x[1])
            return [item[0] + 1 for item in sorted_items]
        return []

    def render_fill_blanks(self, question_data: Dict, q_id: str) -> List[str]:
        """Render fill in the blanks question"""
        blanks_count = question_data['blanks']
        answers = []
        
        st.info(f"Complétez les {blanks_count} blancs dans la phrase")
        
        for i in range(blanks_count):
            answer = st.text_input(
                f"Blanc {i + 1}:",
                key=f"blank_{q_id}_{i}"
            )
            answers.append(answer.strip().lower())
        
        return answers

    def render_matching_pairs(self, question_data: Dict, q_id: str) -> Dict[str, str]:
        """Render matching pairs question"""
        pairs = question_data['pairs']
        items = [pair['item'] for pair in pairs]
        matches = [pair['match'] for pair in pairs]
        
        st.info("Associez chaque élément à sa correspondance")
        
        associations = {}
        for item in items:
            selected_match = st.selectbox(
                item,
                [""] + matches,
                key=f"pair_{q_id}_{item}"
            )
            if selected_match:
                associations[item] = selected_match
        
        return associations

    def render_calculation(self, question_data: Dict, q_id: str) -> float:
        """Render calculation question"""
        if 'formula_hint' in question_data:
            st.info(f"Formule: {question_data['formula_hint']}")
        
        unit = question_data.get('unit', '')
        answer = st.number_input(
            f"Votre réponse{f' ({unit})' if unit else ''}:",
            key=f"calc_{q_id}",
            value=0.0,
            step=0.1
        )
        
        return answer

    def calculate_score(self, question_data: Dict, user_answer: Any) -> Dict[str, Any]:
        """Calculate score for a question based on its type and user answer"""
        q_type = question_data['type']
        
        if q_type == 'multiple_choice':
            correct = question_data['correct_option']
            is_correct = user_answer == correct
            return {
                'correct': is_correct,
                'score': 1 if is_correct else 0,
                'feedback': f"Réponse correcte: Option {correct}" if not is_correct else "Correct!"
            }
        
        elif q_type == 'multiple_select':
            correct_options = set(question_data['correct_options'])
            user_options = set(user_answer) if user_answer else set()
            
            if 'scoring' in question_data:
                scoring = question_data['scoring']
                score = 0
                for option in correct_options:
                    if option in user_options:
                        score += scoring.get('correct_selection', 1)
                    else:
                        score += scoring.get('missed_selection', -0.5)
                
                for option in user_options:
                    if option not in correct_options:
                        score += scoring.get('wrong_selection', -1)
                
                score = max(0, score)  # Minimum score is 0
            else:
                score = 1 if user_options == correct_options else 0
            
            return {
                'correct': user_options == correct_options,
                'score': score,
                'feedback': f"Réponses correctes: {sorted(list(correct_options))}"
            }
        
        elif q_type == 'matching':
            correct_answers = question_data['correct_answers']
            if not user_answer:
                return {'correct': False, 'score': 0, 'feedback': 'Aucune réponse fournie'}
            
            correct_count = sum(1 for item, cat in user_answer.items() 
                              if correct_answers.get(item) == cat)
            total_items = len(correct_answers)
            score = correct_count / total_items
            
            return {
                'correct': score == 1.0,
                'score': score,
                'feedback': f"Correct: {correct_count}/{total_items}"
            }
        
        elif q_type == 'true_false':
            correct = question_data['correct_answer']
            is_correct = user_answer == correct
            feedback = question_data.get('explanation', '')
            
            return {
                'correct': is_correct,
                'score': 1 if is_correct else 0,
                'feedback': feedback if feedback else ("Correct!" if is_correct else f"Réponse correcte: {'Vrai' if correct else 'Faux'}")
            }
        
        elif q_type == 'range_input':
            correct_ranges = question_data['correct_ranges']
            tolerance = question_data.get('tolerance', 5)
            
            if not user_answer:
                return {'correct': False, 'score': 0, 'feedback': 'Aucune réponse fournie'}
            
            correct_count = 0
            total_materials = len(correct_ranges)
            
            for material, correct_range in correct_ranges.items():
                if material in user_answer:
                    user_range = user_answer[material]
                    min_ok = abs(user_range['min'] - correct_range['min']) <= tolerance
                    max_ok = abs(user_range['max'] - correct_range['max']) <= tolerance
                    if min_ok and max_ok:
                        correct_count += 1
            
            score = correct_count / total_materials
            return {
                'correct': score == 1.0,
                'score': score,
                'feedback': f"Ranges corrects: {correct_count}/{total_materials}"
            }
        
        elif q_type == 'calculation':
            correct_answer = question_data['correct_answer']
            tolerance_percent = question_data.get('tolerance_percent', 0)
            
            if user_answer is None:
                return {'correct': False, 'score': 0, 'feedback': 'Aucune réponse fournie'}
            
            tolerance_value = correct_answer * (tolerance_percent / 100)
            is_correct = abs(user_answer - correct_answer) <= tolerance_value
            
            return {
                'correct': is_correct,
                'score': 1 if is_correct else 0,
                'feedback': f"Réponse correcte: {correct_answer} {question_data.get('unit', '')}"
            }
        
        # Add other question type scoring logic here...
        
        return {'correct': False, 'score': 0, 'feedback': 'Type de question non supporté'}

    def render_question(self, question_data: Dict, question_index: int) -> Any:
        """Render a question based on its type"""
        q_type = question_data['type']
        q_id = f"q_{question_index}"
        
        st.subheader(f"Question {question_index + 1}")
        st.write(question_data['question'])
        
        if q_type == 'multiple_choice':
            return self.render_multiple_choice(question_data, q_id)
        elif q_type == 'multiple_select':
            return self.render_multiple_select(question_data, q_id)
        elif q_type == 'matching':
            return self.render_matching(question_data, q_id)
        elif q_type == 'true_false':
            return self.render_true_false(question_data, q_id)
        elif q_type == 'range_input':
            return self.render_range_input(question_data, q_id)
        elif q_type == 'ordering':
            return self.render_ordering(question_data, q_id)
        elif q_type == 'fill_blanks':
            return self.render_fill_blanks(question_data, q_id)
        elif q_type == 'matching_pairs':
            return self.render_matching_pairs(question_data, q_id)
        elif q_type == 'calculation':
            return self.render_calculation(question_data, q_id)
        else:
            st.error(f"Type de question non supporté: {q_type}")
            return None

    def save_to_database(self, questions, user_answers, results):
        """Save evaluation results to database"""
        try:
            # Get or create user
            user_id = st.session_state.db_manager.get_or_create_user(st.session_state.user_name)
            
            if user_id:
                # Get item name
                quiz_data = st.session_state.quiz_data
                selected_item = st.session_state.selected_item
                item_name = quiz_data[selected_item]["item"]
                
                # Save to database
                success = st.session_state.db_manager.save_evaluation_results(
                    user_id, item_name, questions, user_answers, results
                )
                
                if success:
                    st.success("✅ Évaluation sauvegardée avec succès!")
                else:
                    st.error("❌ Erreur lors de la sauvegarde")
            else:
                st.error("❌ Erreur lors de la création de l'utilisateur")
                
        except Exception as e:
            st.error(f"❌ Erreur: {str(e)}")

    def render_quiz(self):
        """Render the quiz for the selected item"""
        quiz_data = st.session_state.quiz_data
        selected_item = st.session_state.selected_item
        current_item = quiz_data[selected_item]
        item_title = current_item["item"]
        questions = current_item["questions"]
        
        # Header with item title and back button
        col1, col2 = st.columns([4, 1])
        with col1:
            st.title(f"📚 {item_title}")
            st.markdown(f"**Étudiant:** {st.session_state.user_name}")
        with col2:
            if st.button("🏠 Menu Principal"):
                st.session_state.selected_item = None
                st.session_state.current_question = 0
                st.session_state.user_answers = {}
                st.session_state.quiz_completed = False
                st.session_state.evaluation_results = []
                # Clear question-specific session state
                for key in list(st.session_state.keys()):
                    if key.startswith(('mc_', 'ms_', 'match_', 'tf_', 'range_', 'order_', 'blank_', 'pair_', 'calc_')):
                        del st.session_state[key]
                st.rerun()

        if not st.session_state.quiz_completed:
            current_q = st.session_state.current_question
            
            if current_q < len(questions):
                question_data = questions[current_q]
                
                # Progress bar
                progress = (current_q + 1) / len(questions)
                st.progress(progress)
                st.write(f"Question {current_q + 1} sur {len(questions)}")
                
                # Render the question
                user_answer = self.render_question(question_data, current_q)
                
                col1, col2 = st.columns(2)
                
                with col1:
                    if st.button("⬅️ Précédent", disabled=current_q == 0):
                        st.session_state.current_question = max(0, current_q - 1)
                        st.rerun()
                
                with col2:
                    if current_q == len(questions) - 1:
                        if st.button("✅ Terminer l'Évaluation"):
                            if user_answer is not None:
                                st.session_state.user_answers[current_q] = user_answer
                                
                                # Calculate all results
                                results = []
                                for i, q_data in enumerate(questions):
                                    if i in st.session_state.user_answers:
                                        user_ans = st.session_state.user_answers[i]
                                        result = self.calculate_score(q_data, user_ans)
                                        results.append(result)
                                
                                st.session_state.evaluation_results = results
                                st.session_state.quiz_completed = True
                                
                                # Save to database
                                self.save_to_database(questions, st.session_state.user_answers, results)
                                st.rerun()
                    else:
                        if st.button("Suivant ➡️"):
                            if user_answer is not None:
                                st.session_state.user_answers[current_q] = user_answer
                                st.session_state.current_question = current_q + 1
                                st.rerun()
                            else:
                                st.warning("Veuillez répondre à la question avant de continuer.")
        
        # Show completion message (no detailed results)
        if st.session_state.quiz_completed:
            st.markdown("---")
            st.header("🎉 Évaluation Terminée!")

            # Add the completed item to the session state list
            item_title = current_item["item"]
            if item_title not in st.session_state.get('completed_quizzes', []):
                st.session_state.completed_quizzes.append(item_title)
            
            # Show only basic completion info
            total_questions = len(questions)
            st.info(f"Vous avez terminé l'évaluation '{item_title}' avec {total_questions} questions.")
            
            # Simple thank you message
            st.success("Merci pour votre participation! Vos réponses ont été enregistrées.")
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🔄 Refaire cette Évaluation", use_container_width=True):
                    # Reset quiz state but keep item selection
                    for key in list(st.session_state.keys()):
                        if key.startswith(('mc_', 'ms_', 'match_', 'tf_', 'range_', 'order_', 'blank_', 'pair_', 'calc_')):
                            del st.session_state[key]
                    st.session_state.current_question = 0
                    st.session_state.user_answers = {}
                    st.session_state.quiz_completed = False
                    st.session_state.evaluation_results = []
                    st.rerun()
            
            with col2:
                if st.button("🏠 Retour au Menu Principal", use_container_width=True):
                    st.session_state.selected_item = None
                    st.session_state.current_question = 0
                    st.session_state.user_answers = {}
                    st.session_state.quiz_completed = False
                    st.session_state.evaluation_results = []
                    # Clear question-specific session state
                    for key in list(st.session_state.keys()):
                        if key.startswith(('mc_', 'ms_', 'match_', 'tf_', 'range_', 'order_', 'blank_', 'pair_', 'calc_')):
                            del st.session_state[key]
                    st.rerun()

    def run(self):
        # Check if user has entered their name
        if not st.session_state.name_submitted:
            self.render_name_input()
        # Check if user has selected an item
        elif st.session_state.selected_item is None:
            self.render_item_selection()
        # Render the quiz for the selected item
        else:
            self.render_quiz()

def main():
    st.set_page_config(
        page_title="Quiz Dynamique",
        page_icon="🎓",
        layout="wide"
    )
    
    app = QuizApp()
    app.run()

if __name__ == "__main__":
    main()