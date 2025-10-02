import streamlit as st
import mysql.connector
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import json

# Database configuration
DB_CONFIG = {
    'host': '127.0.0.1',
    'user': 'root',
    'password': 'root123',
    'database': 'quiz_db2',
    'charset': 'utf8mb4',
    'collation': 'utf8mb4_unicode_ci'
}

class DashboardDBManager:
    """Manages database connections and queries for the dashboard."""
    def __init__(self, config):
        self.config = config

    def connect(self):
        """Establishes a database connection."""
        try:
            return mysql.connector.connect(**self.config)
        except mysql.connector.Error as err:
            st.error(f"Erreur de connexion à la base de données : {err}")
            return None

    def fetch_data_to_df(self, query: str, params=None) -> pd.DataFrame:
        """Fetches data from the database and returns it as a Pandas DataFrame."""
        conn = self.connect()
        if conn is None:
            return pd.DataFrame()
        
        try:
            df = pd.read_sql(query, conn, params=params)
            return df
        except mysql.connector.Error as err:
            st.error(f"Erreur lors de l'exécution de la requête : {err}")
            return pd.DataFrame()
        finally:
            if conn and conn.is_connected():
                conn.close()

def classify_score(score, thresholds):
    """Classifies a score into 'faible', 'moyen', or 'bien' based on thresholds."""
    if score >= thresholds['bien']:
        return 'Bien'
    elif score >= thresholds['moyen']:
        return 'Moyen'
    else:
        return 'Faible'

def generate_dashboard():
    """Main function to generate the Streamlit dashboard."""
    st.set_page_config(
        page_title="Tableau de Bord des Évaluations",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    st.title("📊 Tableau de Bord d'Analyse des Compétences")
    st.markdown("---")

    db_manager = DashboardDBManager(DB_CONFIG)

    # --- Sidebar Filters ---
    st.sidebar.header("Filtres")
    
    # User Filter
    users_df = db_manager.fetch_data_to_df("SELECT username FROM users ORDER BY username")
    if users_df.empty:
        st.sidebar.warning("Aucun utilisateur trouvé.")
        st.stop()
    usernames = users_df['username'].tolist()
    selected_user = st.sidebar.selectbox("Sélectionner un utilisateur :", ["Tous les utilisateurs"] + usernames)

    # Evaluation Item Filter
    item_query = f"""
    SELECT DISTINCT item_name FROM evaluations
    WHERE user_id = (SELECT user_id FROM users WHERE username = %s) OR 'Tous les utilisateurs' = %s
    ORDER BY item_name;
    """
    item_df = db_manager.fetch_data_to_df(item_query, (selected_user, selected_user))
    items = item_df['item_name'].tolist()
    selected_item = st.sidebar.selectbox("Sélectionner un domaine d'évaluation :", ["Tous les domaines"] + items)

    # Question Filter (depends on selected item)
    if selected_item != "Tous les domaines":
        question_query = f"""
        SELECT DISTINCT qr.question_text
        FROM question_results qr
        JOIN evaluations e ON qr.evaluation_id = e.evaluation_id
        WHERE e.item_name = %s
        ORDER BY qr.question_text;
        """
        question_df = db_manager.fetch_data_to_df(question_query, (selected_item,))
        questions = question_df['question_text'].tolist()
        selected_question = st.sidebar.selectbox("Sélectionner une question :", ["Toutes les questions"] + questions)
    else:
        selected_question = "Toutes les questions"
    
    # Dynamic Scoring Sliders
    st.sidebar.markdown("---")
    st.sidebar.header("Seuils de Performance")
    bien_threshold = st.sidebar.slider("Seuil 'Bien' (%)", min_value=0, max_value=100, value=75)
    moyen_threshold = st.sidebar.slider("Seuil 'Moyen' (%)", min_value=0, max_value=100, value=50)
    
    thresholds = {'bien': bien_threshold, 'moyen': moyen_threshold}
    
    # Validate thresholds
    if moyen_threshold >= bien_threshold:
        st.sidebar.error("Le seuil 'Moyen' doit être inférieur au seuil 'Bien'.")
        return # Stop execution if invalid

    # Build dynamic WHERE clause
    where_clauses = []
    query_params = []
    
    if selected_user != "Tous les utilisateurs":
        where_clauses.append("u.username = %s")
        query_params.append(selected_user)
    
    if selected_item != "Tous les domaines":
        where_clauses.append("e.item_name = %s")
        query_params.append(selected_item)
    
    if selected_question != "Toutes les questions":
        where_clauses.append("qr.question_text = %s")
        query_params.append(selected_question)
    
    where_clause_str = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    
    # --- Performance by Evaluation Item (with categories) ---
    st.header("Performance par Domaine d'Évaluation")
    
    # Conditionally add the JOIN for question_results
    join_qr_clause = ""
    if selected_question != "Toutes les questions":
        join_qr_clause = "JOIN question_results qr ON e.evaluation_id = qr.evaluation_id"

    # --- UPDATED QUERY: This query now gets the score of the latest evaluation for each item
    # for the selected user, or for each item across all users if "Tous les utilisateurs" is selected.
    item_perf_query = f"""
    SELECT
        e.item_name,
        e.score_percentage
    FROM evaluations e
    JOIN (
        SELECT user_id, item_name, MAX(evaluation_date) AS latest_date
        FROM evaluations
        GROUP BY user_id, item_name
    ) AS latest_eval ON e.user_id = latest_eval.user_id AND e.item_name = latest_eval.item_name AND e.evaluation_date = latest_eval.latest_date
    JOIN users u ON e.user_id = u.user_id
    {join_qr_clause}
    {where_clause_str}
    ORDER BY e.score_percentage DESC;
    """
    item_perf_df = db_manager.fetch_data_to_df(item_perf_query, tuple(query_params))

    if not item_perf_df.empty:
        
        # --- NOUVEAU: Radar Chart pour la performance globale ---
        if selected_user == "Tous les utilisateurs" and selected_item == "Tous les domaines":
            st.subheader("Performance Globale par Domaine (Radar Chart)")
            
            fig_global_radar = go.Figure()
            fig_global_radar.add_trace(go.Scatterpolar(
                r=item_perf_df['score_percentage'],
                theta=item_perf_df['item_name'],
                fill='toself',
                name='Dernier Score',
                marker=dict(color='blue')
            ))
            
            fig_global_radar.update_layout(
                polar=dict(
                    radialaxis=dict(
                        visible=True,
                        range=[0, 100],
                        tickvals=[0, 25, 50, 75, 100],
                        ticktext=['0%', '25%', '50%', '75%', '100%']
                    )
                ),
                title="Performance Générale par Domaine (Dernier Score)"
            )
            st.plotly_chart(fig_global_radar, use_container_width=True)

        item_perf_df['Catégorie'] = item_perf_df['score_percentage'].apply(lambda x: classify_score(x, thresholds))
        
        # Color mapping for categories
        color_map = {'Bien': 'green', 'Moyen': 'orange', 'Faible': 'red'}
        
        fig_bar = px.bar(
            item_perf_df,
            x="item_name",
            y="score_percentage",
            color="Catégorie",
            color_discrete_map=color_map,
            title="Dernier Score par Domaine (avec classification)",
            labels={"item_name": "Domaine d'Évaluation", "score_percentage": "Score (%)"},
            text="score_percentage"
        )
        fig_bar.update_traces(texttemplate='%{text:.2f}%', textposition='outside')
        fig_bar.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig_bar, use_container_width=True)
    else:
        st.warning("Aucune donnée d'évaluation disponible pour l'affichage.")
    st.markdown("---")

    # --- Distribution des scores pour tous les utilisateurs dans un domaine
    if selected_user == "Tous les utilisateurs" and selected_item != "Tous les domaines":
        st.header(f"📈 Distribution des Scores pour tous les utilisateurs dans le domaine : '{selected_item}'")
        
        distribution_query = f"""
        SELECT
            u.username,
            e.score_percentage
        FROM evaluations e
        JOIN users u ON e.user_id = u.user_id
        WHERE e.item_name = %s
        ORDER BY u.username;
        """
        distribution_df = db_manager.fetch_data_to_df(distribution_query, (selected_item,))
        
        if not distribution_df.empty:
            fig_violin = px.violin(
                distribution_df,
                y="score_percentage",
                x="username",
                color="username",
                box=True, # Display a box plot inside the violin
                points="all", # Display all points
                title=f"Forme de distribution des scores pour tous les utilisateurs dans '{selected_item}'",
                labels={"score_percentage": "Score (%)", "username": "Utilisateur"}
            )
            fig_violin.update_layout(showlegend=False)
            st.plotly_chart(fig_violin, use_container_width=True)
            st.markdown(
                """
                **Interprétation du graphique :**
                * **La forme du violon** montre la densité des scores. Une forme large indique une forte concentration de scores à ce niveau.
                * **La boîte à moustaches (box plot)** à l'intérieur montre les quartiles (25%, 50% et 75%) et la médiane.
                * **Les points** représentent chaque score individuel.
                """
            )
        else:
            st.info(f"Aucune donnée d'évaluation disponible pour le domaine '{selected_item}'.")
    
    st.markdown("---")

    # --- User-specific performance and classification ---
    if selected_user != "Tous les utilisateurs":
        st.header(f"Performance Détaillée de l'Utilisateur: {selected_user}")
        
        # Query for user's all evaluation scores
        user_scores_query = f"""
        SELECT
            e.item_name,
            AVG(e.score_percentage) as average_score,
            COUNT(e.evaluation_id) as total_attempts
        FROM evaluations e
        JOIN users u ON e.user_id = u.user_id
        WHERE u.username = %s
        GROUP BY e.item_name
        ORDER BY average_score DESC;
        """
        user_scores_df = db_manager.fetch_data_to_df(user_scores_query, (selected_user,))
        
        if not user_scores_df.empty:
            
            # --- Radar Chart for Domains ---
            st.subheader("Profil de Compétences (Radar Chart)")
            
            fig_radar_domains = go.Figure()
            fig_radar_domains.add_trace(go.Scatterpolar(
                r=user_scores_df['average_score'],
                theta=user_scores_df['item_name'],
                fill='toself',
                name=selected_user,
                marker=dict(color='blue')
            ))
            
            fig_radar_domains.update_layout(
                polar=dict(
                    radialaxis=dict(
                        visible=True,
                        range=[0, 100],
                        tickvals=[0, 25, 50, 75, 100],
                        ticktext=['0%', '25%', '50%', '75%', '100%']
                    )
                ),
                title=f"Profil de Compétences de {selected_user} par domaine"
            )
            st.plotly_chart(fig_radar_domains, use_container_width=True)

            user_scores_df['Catégorie'] = user_scores_df['average_score'].apply(lambda x: classify_score(x, thresholds))
            
            # Bar chart for user's performance across items
            fig_user_perf = px.bar(
                user_scores_df,
                x="item_name",
                y="average_score",
                color="Catégorie",
                color_discrete_map=color_map,
                title=f"Scores de {selected_user} par domaine",
                labels={"item_name": "Domaine d'Évaluation", "average_score": "Score Moyen (%)"}
            )
            fig_user_perf.update_layout(xaxis_tickangle=-45)
            st.plotly_chart(fig_user_perf, use_container_width=True)
        else:
            st.info(f"Aucune évaluation trouvée pour l'utilisateur {selected_user}.")

    st.markdown("---")

    # --- Performance Over Time, Correct/Incorrect Pie Chart, and NEW Question Radar ---
    if selected_user != "Tous les utilisateurs" and selected_item != "Tous les domaines":
        st.header(f"📈 Analyse Détaillée pour {selected_user} - {selected_item}")

        # --- Radar Chart for questions ---
        if selected_question == "Toutes les questions":
            st.subheader("Performance par Question (Radar Chart)")
            
            question_radar_query = """
            SELECT
                qr.question_text,
                (SUM(qr.is_correct) * 100.0 / COUNT(qr.is_correct)) AS success_rate
            FROM question_results qr
            JOIN evaluations e ON qr.evaluation_id = e.evaluation_id
            JOIN users u ON e.user_id = u.user_id
            WHERE u.username = %s AND e.item_name = %s
            GROUP BY qr.question_text
            ORDER BY qr.question_text;
            """
            question_radar_df = db_manager.fetch_data_to_df(question_radar_query, (selected_user, selected_item))

            if not question_radar_df.empty:
                fig_radar_questions = go.Figure()
                fig_radar_questions.add_trace(go.Scatterpolar(
                    r=question_radar_df['success_rate'],
                    theta=question_radar_df['question_text'],
                    fill='toself',
                    name=selected_user,
                    marker=dict(color='orange')
                ))

                fig_radar_questions.update_layout(
                    polar=dict(
                        radialaxis=dict(
                            visible=True,
                            range=[0, 100],
                            tickvals=[0, 25, 50, 75, 100],
                            ticktext=['0%', '25%', '50%', '75%', '100%']
                        )
                    ),
                    title=f"Taux de Réussite de {selected_user} par Question pour le domaine '{selected_item}'"
                )
                st.plotly_chart(fig_radar_questions, use_container_width=True)
                st.markdown(
                    """
                    **Interprétation :**
                    * Le graphique en toile d'araignée illustre le taux de réussite pour chaque question du domaine sélectionné.
                    * Les points les plus éloignés du centre indiquent une meilleure performance.
                    """
                )
            else:
                st.info("Aucune donnée de question disponible pour ce domaine.")

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Évolution du Score")
            time_query = """
            SELECT evaluation_date, score_percentage
            FROM evaluations e
            JOIN users u ON e.user_id = u.user_id
            WHERE u.username = %s AND e.item_name = %s
            ORDER BY evaluation_date;
            """
            time_df = db_manager.fetch_data_to_df(time_query, (selected_user, selected_item))

            if not time_df.empty:
                fig_time = px.line(
                    time_df,
                    x='evaluation_date',
                    y='score_percentage',
                    markers=True,
                    title=f"Évolution des scores de {selected_user}",
                    labels={'evaluation_date': 'Date', 'score_percentage': 'Score (%)'}
                )
                fig_time.add_hline(y=bien_threshold, line_dash="dash", line_color="green", annotation_text="Seuil Bien", annotation_position="bottom right")
                fig_time.add_hline(y=moyen_threshold, line_dash="dash", line_color="orange", annotation_text="Seuil Moyen", annotation_position="bottom right")
                st.plotly_chart(fig_time, use_container_width=True)
            else:
                st.info("Pas assez de données pour afficher l'évolution du score.")
        
        with col2:
            st.subheader("Répartition des Réponses")
            answers_query = """
            SELECT
                SUM(is_correct) AS correct,
                COUNT(is_correct) - SUM(is_correct) AS incorrect
            FROM question_results qr
            JOIN evaluations e ON qr.evaluation_id = e.evaluation_id
            JOIN users u ON e.user_id = u.user_id
            WHERE u.username = %s AND e.item_name = %s;
            """
            answers_df = db_manager.fetch_data_to_df(answers_query, (selected_user, selected_item))

            if not answers_df.empty and answers_df.iloc[0]['correct'] is not None:
                answers_data = pd.DataFrame({
                    'Réponses': ['Correctes', 'Incorrectes'],
                    'Nombre': [answers_df.iloc[0]['correct'], answers_df.iloc[0]['incorrect']]
                })
                fig_pie = px.pie(
                    answers_data,
                    values='Nombre',
                    names='Réponses',
                    title=f"Répartition des réponses pour '{selected_item}'",
                    color_discrete_map={'Correctes': 'green', 'Incorrectes': 'red'}
                )
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.info("Aucune donnée de question disponible pour cette sélection.")

if __name__ == "__main__":
    generate_dashboard()
