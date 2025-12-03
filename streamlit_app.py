import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import json
import re

# ----------------------------------------------------
# 1. FUNCIÓN DE EXTRACCIÓN Y PROCESAMIENTO DE DATOS
#    (Acepta la clave del partido como argumento)
# ----------------------------------------------------

# El argumento 'match_key' también debe estar en la firma de la caché para que se reejecute solo si la clave cambia.
@st.cache_data
def obtener_y_procesar_datos(match_key):
    # La URL base ahora necesita la clave al final
    url = f"https://www.laliganacional.com.ar/laligaargentina/partido/estadisticas/{match_key}?key="
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Accept-Language': 'es-ES,es;q=0.9',
        'Referer': 'https://www.laliganacional.com.ar/',
        'Connection': 'keep-alive',
    }
    
    st.info(f"Buscando estadísticas para la clave: {match_key}")

    # ⚠️ Manejo de errores de conexión y solicitud
    try:
        response = requests.get(url, headers=headers, timeout=60) # Agregamos un timeout
        response.raise_for_status() # Lanza un error para códigos de estado HTTP malos (4xx o 5xx)
    except requests.exceptions.HTTPError as e:
        if response.status_code == 404:
            st.error(f"Error 404: No se encontró el partido para la clave '{match_key}'. Verifica la clave.")
        else:
            st.error(f"Error HTTP al conectar: {e}")
        return pd.DataFrame() # Retorna un DF vacío si falla
    except requests.exceptions.RequestException as e:
        st.error(f"Error de conexión general: {e}")
        return pd.DataFrame()
        
    html_content = response.text

    # --- Lógica de procesamiento (sin cambios, solo se incluye) ---
    def procesar_html_completo(html):
        soup = BeautifulSoup(html, 'html.parser')
        rows = soup.find_all('tr', attrs={'onclick': True})
        data_list = []
        for row in rows:
            onclick_text = row['onclick']
            match = re.search(r'EstadisticasComponente\((.*?),\s*\'', onclick_text)

            if match:
                json_str = match.group(1)
                try:
                    player_data = json.loads(json_str)
                    data_list.append(player_data)
                except json.JSONDecodeError:
                    continue
        
        return pd.json_normalize(data_list)
    
    df_final = procesar_html_completo(html_content)
    
    if df_final.empty:
        # Esto podría ocurrir si la clave es válida pero la tabla está vacía o el parsing falla.
        st.warning("El procesamiento inicial de la tabla no devolvió datos. Asegúrate de que la clave sea de un partido con estadísticas disponibles.")
        return pd.DataFrame()


    # --- Resto del procesamiento (Celda 3 en adelante) ---
    # Corrección de IdClub e IdEquipo
    rows_with_zero = df_final[df_final['IdClub'] == 0].index
    for idx in rows_with_zero:
        if idx > 0:
            club_id_anterior = df_final.loc[idx - 1, 'IdClub']
            equipo_id_anterior = df_final.loc[idx - 1, 'IdEquipo']
            df_final.loc[idx, 'IdClub'] = club_id_anterior
            df_final.loc[idx, 'IdEquipo'] = equipo_id_anterior
            df_final.loc[idx, 'NombreCompleto'] = 'Equipo'

    # Asignación de Puntos Recibidos
    id_equipos = df_final['IdEquipo'].unique()
    for id_equipo in id_equipos:
        puntos_equipo_contrario = df_final[(df_final['NombreCompleto'] == "Equipo") & (df_final['IdEquipo'] != id_equipo)]['Puntos'].values
        if len(puntos_equipo_contrario) > 0:
            df_final.loc[(df_final['IdEquipo'] == id_equipo) , 'PuntosRecibidos'] = puntos_equipo_contrario[0]

    # Cálculo de Estadísticas Avanzadas
    cols_check = ['TirosDos.Totales', 'TirosTres.Totales', 'TirosLibres.Totales', 'Perdidas', 'ReboteOfensivo', 'ReboteDefensivo', 'Asistencias', 'Puntos', 'PuntosRecibidos']
    for col in cols_check:
        if col not in df_final.columns:
            st.warning(f"La columna necesaria '{col}' no se encontró en los datos, se usará 0.")
            df_final[col] = 0

    df_final['Posesiones'] = (df_final['TirosDos.Totales'] + df_final['TirosTres.Totales'] + 0.44 * df_final['TirosLibres.Totales'] + df_final['Perdidas'] - df_final['ReboteOfensivo'])
    
    # Manejo de divisiones por cero para los cálculos de eficiencia
    df_final['EficienciaOfensiva'] = df_final['Puntos'] / df_final['Posesiones'].replace(0, float('nan'))
    df_final['EficienciaDefensiva'] = df_final['PuntosRecibidos'] / df_final['Posesiones'].replace(0, float('nan'))
    df_final['Net Rating'] = df_final['EficienciaOfensiva'] - df_final['EficienciaDefensiva']
    
    df_equipos = df_final[df_final['NombreCompleto'] == 'Equipo']
    rebotes_totales = sum(df_equipos['ReboteDefensivo'] + df_equipos['ReboteOfensivo'])
    if rebotes_totales > 0:
        df_final['perc_reb_totales'] = 100* (df_final['ReboteDefensivo'] + df_final['ReboteOfensivo']) / rebotes_totales
    else:
        df_final['perc_reb_totales'] = 0

    df_final['perc_asistencias'] = 100* df_final['Asistencias'] / df_final['Posesiones'].replace(0, float('nan'))
    df_final['perc_perdidas'] = 100* df_final['Perdidas'] / df_final['Posesiones'].replace(0, float('nan'))
    df_final['perc_robos'] = 100* df_final['Recuperaciones'] / df_final['Posesiones'].replace(0, float('nan'))
    df_final['perc_bloqueos'] = 100* df_final['TaponCometido'] / df_final['Posesiones'].replace(0, float('nan'))
    df_final['3p_fg'] = 100* df_final['TirosTres.Totales'] / (df_final['TirosDos.Totales'] + df_final['TirosTres.Totales']).replace(0, float('nan'))

    
    df_final = df_final.replace([float('inf'), -float('inf')], float('nan'))
    
    st.success("¡Datos cargados y procesados con éxito!")

    return df_final


# ----------------------------------------------------
# 2. INTERFAZ DE STREAMLIT (Añadiendo Input de Key)
# ----------------------------------------------------

def main():
    st.set_page_config(layout="wide")
    st.title('🏀 Estadísticas Avanzadas de la Liga Argentina')
    st.markdown('***')

    # Campo de entrada para la clave del partido
    match_key = st.text_input(
        'Introduce la CLAVE del partido (la parte final de la URL, e.g., j3YB7iwG6VLepKd_HqtAyg==)',
        # Puedes poner una clave de ejemplo para testear
        value='' 
    )

    # Agregar botón de refresh
    col1, col2 = st.columns([4, 1])
    with col2:
        refresh_button = st.button('🔄 Refrescar')
    
    if refresh_button:
        st.cache_data.clear()
        st.rerun()

    if match_key:
        # Si se ingresa una clave, llama a la función de procesamiento
        df = obtener_y_procesar_datos(match_key)

        if df.empty:
            # Si el DF está vacío (hubo un error o no hay datos), no mostrar más la interfaz
            return

        # --- Sidebar y Filtros ---
        st.sidebar.header('Filtros')
        
        # Filtro de Equipos (basado en IdClub)
        club_ids = df['IdClub'].unique()
        selected_club_id = st.sidebar.selectbox('Seleccionar ID de Club:', club_ids)
        
        # Aplicar filtro
        df_filtered = df[df['IdClub'] == selected_club_id]

        df_players = df_filtered[df_filtered['NombreCompleto'] != 'Equipo']
        df_team_summary = df_filtered[df_filtered['NombreCompleto'] == 'Equipo']


        # --- Pestañas para organizar la visualización ---
        tab_equipos, tab_jugadores = st.tabs([ "📈 Resumen por Equipo","📊 Jugadores (Estadísticas Avanzadas)"])

        

        # Pestaña de Resumen por Equipo
        with tab_equipos:
            if not df_team_summary.empty:
                st.header(f"Resumen de Eficiencia del Club ID: {selected_club_id}")
                
                summary_cols = ['Puntos', 'PuntosRecibidos', 'Posesiones', 'EficienciaOfensiva', 'EficienciaDefensiva', 'Net Rating', 'perc_reb_totales', 'perc_asistencias',
                                'perc_perdidas', 'perc_robos', 'perc_bloqueos', '3p_fg']
                summary_df_display = df_team_summary[summary_cols].transpose()
                
                summary_df_display.index = [
                    'Puntos Anotados', 'Puntos Recibidos', 'Posesiones Estimadas', 
                    'Eficiencia Ofensiva (Puntos/100 Pos)', 
                    'Eficiencia Defensiva (Ptos Recibidos/100 Pos)', 
                    'Net Rating (EO - ED)',
                    '% Rebotes Totales del Equipo',
                    '% Asistencias del Equipo',
                    '% Pérdidas del Equipo',
                    '% Robos del Equipo',   
                    '% Bloqueos Cometidos del Equipo',
                    '% 3P FG'
                ]
                
                summary_df_display.columns = ['Valor']
                
                st.table(summary_df_display.style.format({
                    'Valor': "{:.2f}"
                }))
            else:
                st.warning("No se encontró el resumen del equipo en los datos filtrados.")


        # Pestaña de Jugadores
        with tab_jugadores:
            st.header(f"Jugadores del Club ID: {selected_club_id}")
            
            player_cols = [
                'NombreCompleto', 'Minutos', 'Puntos', 'EficienciaOfensiva', 
                'Net Rating', 'perc_reb_totales', 'perc_asistencias'
            ]
            
            df_display = df_players[player_cols].copy()
            df_display.columns = [
                'Jugador', 'Minutos', 'Puntos', 'Eficiencia Ofensiva (EO)', 
                'Net Rating', '% Rebotes Totales', '% Asistencias'
            ]
            
            st.dataframe(
                df_display,
                hide_index=True,
                column_config={
                    'Eficiencia Ofensiva (EO)': st.column_config.NumberColumn(format="%.3f"),
                    'Net Rating': st.column_config.NumberColumn(format="%.3f"),
                    '% Rebotes Totales': st.column_config.NumberColumn(format="%.1%"),
                    '% Asistencias': st.column_config.NumberColumn(format="%.1%"),
                }
            )
    else:
        # Mensaje si no hay clave introducida
        st.info("Por favor, introduce la clave de un partido de la Liga Nacional para ver las estadísticas avanzadas.")


if __name__ == '__main__':
    main()