from dataclasses import dataclass
import re
from .Distances import distances


@dataclass
class Endereco:
    cep: str
    rua: str
    numero: str
    complemento: str
    bairro: str
    cidade: str
    estado: str


class Validacao_endereco:
    
    def __init__(self, cartao_proposta_endereco, dados_extraidos_endereco):
        self.cartao_proposta = Endereco(**cartao_proposta_endereco)
        self.dados_extraidos = Endereco(**dados_extraidos_endereco)
    
    def validar_cep(self):
        s1 = ''.join(re.findall( r'\d+', self.cartao_proposta.cep))
        s2 = ''.join(re.findall(r'\d+', self.dados_extraidos.cep))
        if s1 == s2:
            return True
        else:
            return False
            
            
    def validar_rua(self, limiar=60):
        s1 = self.cartao_proposta.rua
        s2 = self.dados_extraidos.rua
        
        sim_score = distances(s1.upper(), s2.upper()).norm_score()
        if sim_score >=limiar:
            return True
        else:
            return False
            
            
    def validar_numero(self):
        
        s1 = self.cartao_proposta.numero
        s2 = self.dados_extraidos.numero
        
        if(s2 == 'Not Found'):
            s2 = '' 
            self.dados_extraidos.numero = ''

        try: 
            s1 = int(s1)
            s2 = int(s2)
            
            if s1 == s2:
                return True
            else:
                return False
        except:
            return False
    
    
    def _preprocessamento_complemento(self, complemento):
        if(complemento == 'Not Found'):
            self.dados_extraidos.complemento = ''
            return '' 
        
        # remove pontuacoes
        complemento = re.sub(r'[^\w\s]',' ', complemento)
    
        # remove espacos em branco extras
        complemento = re.sub(' +', ' ', complemento)
    
        # resume palavra (exemplo: apto, apt, apartamento) a primeira letra
        complemento = (lambda complemento: ' '.join([comp[0] if comp.isalpha() else comp for comp in complemento.split(' ')]))(complemento)
        
        return complemento
        
        
    def validar_complemento(self, limiar=90):
        s1 = self.cartao_proposta.complemento
        s2 = self.dados_extraidos.complemento
        
        s1 = self._preprocessamento_complemento(s1)
        s2 = self._preprocessamento_complemento(s2)
        
        sim_score = distances(s1.upper(), s2.upper()).norm_score()
        if sim_score >= limiar:
            return True
        else:
            return False


    def validar_bairro(self, limiar=60):
        s1 = self.cartao_proposta.bairro
        s2 = self.dados_extraidos.bairro
        
        sim_score = distances(s1.upper(), s2.upper()).norm_score()
        if sim_score >= limiar:
            return True
        else:
            return False
            
    def validar_cidade(self, limiar=60):
        s1 = self.cartao_proposta.cidade
        s2 = self.dados_extraidos.cidade
        
        sim_score = distances(s1.upper(), s2.upper()).norm_score()
        if sim_score >= limiar:
            return True
        else:
            return False
    
    def validar_estado(self):
        s1 = self.cartao_proposta.estado
        s2 = self.dados_extraidos.estado
        
        if s1 == s2:
            return True
        else:
            return False
        
    
    def validar_endereco(self, limiar=0.7):
        
        validados = 0
        validados += (lambda: 1 if self.validar_cep() else 0)()
        validados += (lambda: 1 if self.validar_rua() else 0)()
        validados += (lambda: 1 if self.validar_numero() else 0)()
        validados += (lambda: 1 if self.validar_complemento() else 0)()
        validados += (lambda: 1 if self.validar_bairro() else 0)()
        validados += (lambda: 1 if self.validar_cidade() else 0)()
        validados += (lambda: 1 if self.validar_estado() else 0)()
        
        score = validados/7
        if(score >= limiar):
            return True, int(score*100)
        else:
            return False, int(score*100)